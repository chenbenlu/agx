from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import pandas as pd
import torch

from .modeling import (
    GroundingDINOModelRunner,
    default_grounding_dino_repo_path,
    draw_detections,
)


def parse_args() -> argparse.Namespace:
    repo_guess = default_grounding_dino_repo_path()
    config_guess = repo_guess / "groundingdino/config/GroundingDINO_SwinT_OGC.py"
    weights_guess = Path(__file__).resolve().parents[2] / "weights/groundingdino_swint_ogc.pth"

    parser = argparse.ArgumentParser(
        description="Run GroundingDINO on a single image without using live ROS topics."
    )
    parser.add_argument(
        "--image-path",
        type=Path,
        required=True,
        help="Path to the input image.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="Dot-separated text prompt, e.g. 'person. traffic cone.'.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for outputs. Defaults to the input image directory.",
    )
    parser.add_argument(
        "--grounding-dino-repo-path",
        type=Path,
        default=repo_guess,
        help="Path to the GroundingDINO repository.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=config_guess,
        help="GroundingDINO config path.",
    )
    parser.add_argument(
        "--weights-path",
        type=Path,
        default=weights_guess,
        help="GroundingDINO checkpoint path.",
    )
    parser.add_argument(
        "--box-threshold",
        type=float,
        default=0.35,
        help="Minimum detection confidence threshold.",
    )
    parser.add_argument(
        "--text-threshold",
        type=float,
        default=0.25,
        help="Phrase token threshold.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Execution device, typically cuda on AGX Orin.",
    )
    parser.add_argument(
        "--use-fp16",
        action="store_true",
        help="Use AMP FP16 inference when running on CUDA.",
    )
    parser.add_argument(
        "--save-csv",
        action="store_true",
        help="Also save detections as CSV.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    image_path = args.image_path.expanduser().resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else image_path.parent
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    image_bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    runner = GroundingDINOModelRunner(
        repo_path=args.grounding_dino_repo_path,
        config_path=args.config_path,
        weights_path=args.weights_path,
        device=args.device,
        use_fp16=args.use_fp16,
    )

    detections = runner.predict(
        image_bgr=image_bgr,
        prompt=args.prompt,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
    )

    annotated = draw_detections(image_bgr=image_bgr, detections=detections)
    annotated_path = output_dir / f"{image_path.stem}_grounding_dino.jpg"
    cv2.imwrite(str(annotated_path), annotated)

    rows = []
    for det in detections:
        rows.append(
            {
                "label": det.phrase,
                "score": det.score,
                "x1": float(det.xyxy[0]),
                "y1": float(det.xyxy[1]),
                "x2": float(det.xyxy[2]),
                "y2": float(det.xyxy[3]),
                "cx": float(det.cxcywh[0]),
                "cy": float(det.cxcywh[1]),
                "w": float(det.cxcywh[2]),
                "h": float(det.cxcywh[3]),
            }
        )

    print(f"Image: {image_path}")
    print(f"Prompt: {args.prompt}")
    print(f"Detections: {len(rows)}")
    for idx, row in enumerate(rows, start=1):
        print(
            f"{idx}. {row['label']} score={row['score']:.3f} "
            f"bbox=[{row['x1']:.1f}, {row['y1']:.1f}, {row['x2']:.1f}, {row['y2']:.1f}]"
        )

    print(f"Annotated image saved to: {annotated_path}")

    if args.save_csv:
        csv_path = output_dir / f"{image_path.stem}_grounding_dino.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        print(f"Detection CSV saved to: {csv_path}")


if __name__ == "__main__":
    main()
