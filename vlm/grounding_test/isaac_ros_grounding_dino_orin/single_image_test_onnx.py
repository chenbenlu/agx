#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = REPO_ROOT / "./demo.png"
DEFAULT_ONNX = REPO_ROOT / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx"
MAX_TEXT_LENGTH = 256
IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass
class ImageTransformInfo:
    original_width: int
    original_height: int
    resized_width: int
    resized_height: int
    scale_x: float
    scale_y: float
    network_width: int
    network_height: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone single-image Grounding DINO ONNX test for AGX Orin."
    )
    parser.add_argument(
        "--image-path",
        type=Path,
        default=DEFAULT_IMAGE,
        help="Input image path.",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_ONNX,
        help="Path to Grounding DINO ONNX model.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="Dot-separated prompt, e.g. 'person. traffic cone.'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to the input image directory.",
    )
    parser.add_argument(
        "--box-threshold",
        type=float,
        default=0.35,
        help="Detection score threshold after label scoring.",
    )
    parser.add_argument(
        "--text-threshold",
        type=float,
        default=0.25,
        help="Reserved for compatibility; ONNX decoder path uses positive map scoring.",
    )
    parser.add_argument(
        "--network-width",
        type=int,
        default=960,
        help="Model input width if it cannot be inferred from ONNX.",
    )
    parser.add_argument(
        "--network-height",
        type=int,
        default=544,
        help="Model input height if it cannot be inferred from ONNX.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda",
        choices=["cuda", "cpu"],
        help="Inference device for ONNX Runtime.",
    )
    parser.add_argument(
        "--save-csv",
        action="store_true",
        help="Save detections to CSV.",
    )
    return parser.parse_args()


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def candidate_model_paths() -> list[Path]:
    candidates = [
        REPO_ROOT / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx",
        REPO_ROOT.parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx",
        REPO_ROOT.parent.parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx",
        Path.cwd() / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx",
        Path.cwd().parent / "isaac_ros_assets/models/grounding_dino/grounding_dino_model.onnx",
    ]
    unique = []
    seen = set()
    for path in candidates:
        resolved = path.expanduser().resolve()
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        unique.append(resolved)
    return unique


def resolve_model_path(requested_model: Path) -> Path:
    requested_model = requested_model.expanduser().resolve()
    if requested_model.exists():
        return requested_model

    for candidate in candidate_model_paths():
        if candidate.exists():
            return candidate

    searched = "\n".join(f"- {path}" for path in candidate_model_paths())
    raise FileNotFoundError(
        "Could not find Grounding DINO ONNX model.\n"
        "Searched these locations:\n"
        f"{searched}\n"
        "Pass the correct path explicitly with --model-path."
    )


def preprocess_caption(caption: str) -> str:
    caption = caption.lower().strip()
    return caption if caption.endswith(".") else caption + "."


def create_tokenizer():
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `transformers`. Install it in the AGX Orin environment."
        ) from exc

    try:
        return AutoTokenizer.from_pretrained("bert-base-uncased", local_files_only=True)
    except OSError:
        return AutoTokenizer.from_pretrained("bert-base-uncased")


def generate_text_token_mask_and_position_ids(tokenized: dict[str, np.ndarray], special_token_ids):
    input_ids = tokenized["input_ids"].squeeze(0)
    num_token = len(input_ids)
    special_positions = np.where(np.isin(input_ids, special_token_ids))[0]

    text_token_mask = np.eye(num_token, dtype=np.uint8)
    position_ids = np.zeros(num_token, dtype=np.int64)

    previous_col = 0
    for col in special_positions:
        if col not in (0, num_token - 1):
            text_token_mask[previous_col + 1 : col + 1, previous_col + 1 : col + 1] = 1
            position_ids[previous_col + 1 : col + 1] = np.arange(col - previous_col)
            previous_col = col

    return (
        text_token_mask[np.newaxis, :MAX_TEXT_LENGTH, :MAX_TEXT_LENGTH],
        position_ids[np.newaxis, :MAX_TEXT_LENGTH],
    )


def create_positive_map(tokenized, class_ids: list[str], text: str) -> np.ndarray:
    pos_map = np.zeros((len(class_ids), MAX_TEXT_LENGTH), dtype=np.uint8)

    for idx, category in enumerate(class_ids):
        start_char = text.find(category)
        end_char = start_char + len(category) - 1
        start_token = tokenized.char_to_token(start_char)
        end_token = tokenized.char_to_token(end_char)
        if end_token is None and end_char > 0:
            end_token = tokenized.char_to_token(end_char - 1)
        if end_token is None and end_char > 1:
            end_token = tokenized.char_to_token(end_char - 2)

        if start_token is not None and end_token is not None and start_token <= end_token:
            pos_map[idx, start_token : end_token + 1] = 1

    return pos_map


def tokenize_prompt(tokenizer, prompt: str):
    prompt = preprocess_caption(prompt)
    tokenized_np = tokenizer(
        prompt,
        padding="max_length",
        return_tensors="np",
        max_length=MAX_TEXT_LENGTH,
        truncation=True,
    )
    tokenized_fast = tokenizer(
        prompt,
        padding="max_length",
        return_tensors="np",
        max_length=MAX_TEXT_LENGTH,
        truncation=True,
        return_offsets_mapping=True,
    )

    class_ids = [item.strip() for item in prompt.split(".") if item.strip()]
    special_tokens = ["[CLS]", "[SEP]", ".", "?"]
    special_token_ids = tokenizer.convert_tokens_to_ids(special_tokens)
    text_token_mask, position_ids = generate_text_token_mask_and_position_ids(
        tokenized_np, special_token_ids
    )
    positive_map = create_positive_map(tokenized_fast, class_ids, prompt)

    text_inputs = {
        "input_ids": tokenized_np["input_ids"][:, :MAX_TEXT_LENGTH].astype(np.int64),
        "attention_mask": tokenized_np["attention_mask"][:, :MAX_TEXT_LENGTH].astype(np.uint8),
        "token_type_ids": tokenized_np["token_type_ids"][:, :MAX_TEXT_LENGTH].astype(np.int64),
        "position_ids": position_ids.astype(np.int64),
        "text_token_mask": text_token_mask.astype(np.uint8),
    }
    return text_inputs, positive_map.astype(np.float32), class_ids, prompt


def infer_network_size(session, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    for input_meta in session.get_inputs():
        if input_meta.name.lower() in {"inputs", "images", "image", "input"}:
            shape = input_meta.shape
            if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
                return int(shape[3]), int(shape[2])
    return fallback_width, fallback_height


def resize_and_pad_image(
    image_bgr: np.ndarray,
    network_width: int,
    network_height: int,
) -> tuple[np.ndarray, ImageTransformInfo]:
    original_height, original_width = image_bgr.shape[:2]
    scale = min(network_width / original_width, network_height / original_height)
    resized_width = max(1, int(round(original_width * scale)))
    resized_height = max(1, int(round(original_height * scale)))

    resized = cv2.resize(image_bgr, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    canvas = np.zeros((network_height, network_width, 3), dtype=np.uint8)
    canvas[:resized_height, :resized_width] = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

    info = ImageTransformInfo(
        original_width=original_width,
        original_height=original_height,
        resized_width=resized_width,
        resized_height=resized_height,
        scale_x=resized_width / original_width,
        scale_y=resized_height / original_height,
        network_width=network_width,
        network_height=network_height,
    )
    return canvas, info


def preprocess_image(
    image_bgr: np.ndarray,
    network_width: int,
    network_height: int,
) -> tuple[np.ndarray, ImageTransformInfo]:
    rgb_padded, info = resize_and_pad_image(image_bgr, network_width, network_height)
    image = rgb_padded.astype(np.float32) / 255.0
    image = (image - IMAGE_MEAN) / IMAGE_STD
    image = np.transpose(image, (2, 0, 1))
    image = np.expand_dims(image, axis=0).astype(np.float32)
    return image, info


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def decode_scores(pred_logits: np.ndarray, positive_map: np.ndarray) -> np.ndarray:
    prob_to_token = sigmoid(pred_logits)
    row_sums = positive_map.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    pos_map_normalized = positive_map / row_sums
    return prob_to_token @ pos_map_normalized.T


def convert_boxes_to_original(pred_boxes: np.ndarray, info: ImageTransformInfo) -> np.ndarray:
    cx = pred_boxes[:, 0] * info.network_width
    cy = pred_boxes[:, 1] * info.network_height
    bw = pred_boxes[:, 2] * info.network_width
    bh = pred_boxes[:, 3] * info.network_height

    x1 = cx - bw / 2.0
    y1 = cy - bh / 2.0
    x2 = cx + bw / 2.0
    y2 = cy + bh / 2.0

    x1 = np.clip(x1, 0, info.resized_width)
    y1 = np.clip(y1, 0, info.resized_height)
    x2 = np.clip(x2, 0, info.resized_width)
    y2 = np.clip(y2, 0, info.resized_height)

    x1 = x1 / info.scale_x
    y1 = y1 / info.scale_y
    x2 = x2 / info.scale_x
    y2 = y2 / info.scale_y

    x1 = np.clip(x1, 0, info.original_width - 1)
    y1 = np.clip(y1, 0, info.original_height - 1)
    x2 = np.clip(x2, 0, info.original_width - 1)
    y2 = np.clip(y2, 0, info.original_height - 1)
    return np.stack([x1, y1, x2, y2], axis=1).astype(np.float32)


def draw_detections(image_bgr: np.ndarray, detections: list[dict[str, float | str]]) -> np.ndarray:
    annotated = image_bgr.copy()
    for det in detections:
        x1, y1, x2, y2 = int(det["x1"]), int(det["y1"]), int(det["x2"]), int(det["y2"])
        label = f"{det['label']} {float(det['score']):.2f}"
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


def create_session(model_path: Path, device: str):
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `onnxruntime`. Install `onnxruntime-gpu` or `onnxruntime` on AGX Orin."
        ) from exc

    available = ort.get_available_providers()
    if device == "cuda" and "CUDAExecutionProvider" in available:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]
    try:
        session = ort.InferenceSession(str(model_path), providers=providers)
    except Exception as exc:
        message = str(exc)
        if "MultiscaleDeformableAttnPlugin_TRT" in message:
            raise RuntimeError(
                "This Grounding DINO ONNX cannot be executed directly with plain ONNX Runtime.\n"
                "The model contains the TensorRT custom op `MultiscaleDeformableAttnPlugin_TRT`.\n"
                "That means this file is intended for TensorRT-based execution, not generic ONNX Runtime.\n"
                "Use the existing TensorRT engine `.plan` instead, or run it through Isaac ROS TensorRTNode."
            ) from exc
        raise
    return session, providers


def resolve_input_name(actual_names: list[str], aliases: list[str]) -> str:
    lowered = {name.lower(): name for name in actual_names}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    raise KeyError(f"Could not resolve input/output name from aliases: {aliases}")


def run_inference(
    session,
    image_tensor: np.ndarray,
    text_inputs: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    input_names = [meta.name for meta in session.get_inputs()]
    output_names = [meta.name for meta in session.get_outputs()]

    feed = {
        resolve_input_name(input_names, ["inputs", "images", "image", "input"]): image_tensor,
        resolve_input_name(input_names, ["input_ids"]): text_inputs["input_ids"],
        resolve_input_name(input_names, ["attention_mask"]): text_inputs["attention_mask"],
        resolve_input_name(input_names, ["position_ids"]): text_inputs["position_ids"],
        resolve_input_name(input_names, ["token_type_ids"]): text_inputs["token_type_ids"],
        resolve_input_name(input_names, ["text_token_mask"]): text_inputs["text_token_mask"],
    }

    scores_name = resolve_input_name(output_names, ["pred_logits", "scores"])
    boxes_name = resolve_input_name(output_names, ["pred_boxes", "boxes"])
    outputs = session.run([scores_name, boxes_name], feed)
    pred_logits = outputs[0][0].astype(np.float32)
    pred_boxes = outputs[1][0].astype(np.float32)
    return pred_logits, pred_boxes


def main() -> None:
    args = parse_args()

    image_path = args.image_path.expanduser().resolve()
    model_path = resolve_model_path(args.model_path)
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else image_path.parent
    )

    ensure_exists(image_path, "Input image")
    output_dir.mkdir(parents=True, exist_ok=True)

    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    tokenizer = create_tokenizer()
    text_inputs, positive_map, class_ids, normalized_prompt = tokenize_prompt(tokenizer, args.prompt)
    session, providers = create_session(model_path, args.device)
    network_width, network_height = infer_network_size(
        session, fallback_width=args.network_width, fallback_height=args.network_height
    )
    image_tensor, transform_info = preprocess_image(
        image_bgr, network_width=network_width, network_height=network_height
    )
    pred_logits, pred_boxes = run_inference(session, image_tensor, text_inputs)

    label_scores = decode_scores(pred_logits, positive_map)
    boxes_xyxy = convert_boxes_to_original(pred_boxes, transform_info)

    detections = []
    for query_idx in range(label_scores.shape[0]):
        for label_idx, class_name in enumerate(class_ids):
            score = float(label_scores[query_idx, label_idx])
            if score <= args.box_threshold:
                continue
            box = boxes_xyxy[query_idx]
            detections.append(
                {
                    "label": class_name,
                    "score": score,
                    "x1": float(box[0]),
                    "y1": float(box[1]),
                    "x2": float(box[2]),
                    "y2": float(box[3]),
                }
            )

    detections.sort(key=lambda item: float(item["score"]), reverse=True)
    annotated = draw_detections(image_bgr, detections)
    annotated_path = output_dir / f"{image_path.stem}_grounding_dino_onnx.jpg"
    cv2.imwrite(str(annotated_path), annotated)

    print(f"Image: {image_path}")
    print(f"Model: {model_path}")
    print(f"Providers: {providers}")
    print(f"Prompt: {normalized_prompt}")
    print(f"Network size: {network_width}x{network_height}")
    print(f"Detections: {len(detections)}")
    for idx, det in enumerate(detections, start=1):
        print(
            f"{idx}. {det['label']} score={float(det['score']):.3f} "
            f"bbox=[{float(det['x1']):.1f}, {float(det['y1']):.1f}, "
            f"{float(det['x2']):.1f}, {float(det['y2']):.1f}]"
        )
    print(f"Annotated image saved to: {annotated_path}")

    if args.save_csv:
        csv_path = output_dir / f"{image_path.stem}_grounding_dino_onnx.csv"
        pd.DataFrame(detections).to_csv(csv_path, index=False)
        print(f"Detection CSV saved to: {csv_path}")


if __name__ == "__main__":
    main()
