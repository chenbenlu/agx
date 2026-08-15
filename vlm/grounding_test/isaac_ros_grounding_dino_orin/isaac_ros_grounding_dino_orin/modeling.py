from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
import importlib
import sys
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image


@dataclass
class DetectionResult:
    phrase: str
    score: float
    xyxy: np.ndarray
    cxcywh: np.ndarray


def preprocess_caption(caption: str) -> str:
    result = caption.lower().strip()
    if result.endswith("."):
        return result
    return result + "."


def default_grounding_dino_repo_path() -> Path:
    return Path(__file__).resolve().parents[2] / "GroundingDINO"


def ensure_grounding_dino_importable(repo_path: str | Path) -> Path:
    repo_path = Path(repo_path).expanduser().resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"GroundingDINO repo not found: {repo_path}")

    repo_str = str(repo_path)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    return repo_path


def import_grounding_dino_modules(repo_path: str | Path) -> dict[str, Any]:
    ensure_grounding_dino_importable(repo_path)
    modules = {
        "transforms": importlib.import_module("groundingdino.datasets.transforms"),
        "build_model": importlib.import_module("groundingdino.models").build_model,
        "clean_state_dict": importlib.import_module("groundingdino.util.misc").clean_state_dict,
        "SLConfig": importlib.import_module("groundingdino.util.slconfig").SLConfig,
        "get_phrases_from_posmap": importlib.import_module(
            "groundingdino.util.utils"
        ).get_phrases_from_posmap,
    }
    return modules


def cxcywh_to_xyxy(boxes_cxcywh: np.ndarray, width: int, height: int) -> np.ndarray:
    scaled = boxes_cxcywh.astype(np.float32).copy()
    scaled[:, 0] *= width
    scaled[:, 1] *= height
    scaled[:, 2] *= width
    scaled[:, 3] *= height

    xyxy = np.empty_like(scaled)
    xyxy[:, 0] = scaled[:, 0] - (scaled[:, 2] / 2.0)
    xyxy[:, 1] = scaled[:, 1] - (scaled[:, 3] / 2.0)
    xyxy[:, 2] = scaled[:, 0] + (scaled[:, 2] / 2.0)
    xyxy[:, 3] = scaled[:, 1] + (scaled[:, 3] / 2.0)

    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, width - 1)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, height - 1)
    return xyxy


class GroundingDINOModelRunner:
    def __init__(
        self,
        repo_path: str | Path,
        config_path: str | Path,
        weights_path: str | Path,
        device: str = "cuda",
        use_fp16: bool = False,
    ) -> None:
        self.repo_path = ensure_grounding_dino_importable(repo_path)
        self.modules = import_grounding_dino_modules(self.repo_path)
        self.device = torch.device(device)
        self.use_fp16 = bool(use_fp16 and self.device.type == "cuda")

        config_path = Path(config_path).expanduser().resolve()
        weights_path = Path(weights_path).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        if not weights_path.exists():
            raise FileNotFoundError(f"Weights not found: {weights_path}")

        self.transform = self.modules["transforms"].Compose(
            [
                self.modules["transforms"].RandomResize([800], max_size=1333),
                self.modules["transforms"].ToTensor(),
                self.modules["transforms"].Normalize(
                    [0.485, 0.456, 0.406],
                    [0.229, 0.224, 0.225],
                ),
            ]
        )

        args = self.modules["SLConfig"].fromfile(str(config_path))
        args.device = str(self.device)
        model = self.modules["build_model"](args)
        checkpoint = torch.load(str(weights_path), map_location="cpu")
        model.load_state_dict(
            self.modules["clean_state_dict"](checkpoint["model"]),
            strict=False,
        )
        model.eval()
        model.to(self.device)
        self.model = model

    def preprocess_image(self, image_bgr: np.ndarray) -> torch.Tensor:
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        image_pillow = Image.fromarray(image_rgb)
        image_tensor, _ = self.transform(image_pillow, None)
        return image_tensor

    def predict(
        self,
        image_bgr: np.ndarray,
        prompt: str,
        box_threshold: float,
        text_threshold: float,
    ) -> list[DetectionResult]:
        caption = preprocess_caption(prompt)
        image_tensor = self.preprocess_image(image_bgr=image_bgr).to(self.device)

        autocast_context = (
            torch.autocast(device_type="cuda", dtype=torch.float16)
            if self.use_fp16
            else nullcontext()
        )

        with torch.inference_mode(), autocast_context:
            outputs = self.model(image_tensor[None], captions=[caption])

        pred_logits = outputs["pred_logits"].detach().float().cpu().sigmoid()[0]
        pred_boxes = outputs["pred_boxes"].detach().float().cpu()[0]

        keep = pred_logits.max(dim=1)[0] > box_threshold
        kept_logits = pred_logits[keep]
        kept_boxes = pred_boxes[keep]
        if kept_boxes.numel() == 0:
            return []

        tokenizer = self.model.tokenizer
        tokenized = tokenizer(caption)
        phrases = [
            self.modules["get_phrases_from_posmap"](
                logit > text_threshold,
                tokenized,
                tokenizer,
            ).replace(".", "").strip()
            for logit in kept_logits
        ]

        scores = kept_logits.max(dim=1)[0].numpy()
        boxes_cxcywh = kept_boxes.numpy()
        height, width = image_bgr.shape[:2]
        boxes_xyxy = cxcywh_to_xyxy(boxes_cxcywh, width=width, height=height)

        results: list[DetectionResult] = []
        for phrase, score, xyxy, cxcywh in zip(phrases, scores, boxes_xyxy, boxes_cxcywh):
            results.append(
                DetectionResult(
                    phrase=phrase or "object",
                    score=float(score),
                    xyxy=xyxy.astype(np.float32),
                    cxcywh=cxcywh.astype(np.float32),
                )
            )
        return results


def draw_detections(image_bgr: np.ndarray, detections: list[DetectionResult]) -> np.ndarray:
    annotated = image_bgr.copy()
    for det in detections:
        x1, y1, x2, y2 = det.xyxy.astype(int)
        label = f"{det.phrase} {det.score:.2f}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (40, 220, 120), 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(y1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (40, 220, 120),
            2,
            cv2.LINE_AA,
        )
    return annotated
