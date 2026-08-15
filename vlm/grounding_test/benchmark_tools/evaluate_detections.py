#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt-csv", type=str, required=True)
    parser.add_argument("--pred-csv", type=str, required=True)
    parser.add_argument("--output-csv", type=str, required=True)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument(
        "--pred-label-mode",
        type=str,
        default="auto",
        choices=["auto", "raw", "yolo_coco80"],
        help="How to interpret prediction labels",
    )
    parser.add_argument(
        "--classes",
        type=str,
        default="",
        help="Comma-separated class subset. Leave empty to use GT classes.",
    )
    return parser.parse_args()


def normalize_label(label: str) -> str:
    text = str(label).strip().lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def decode_pred_label(label_raw: str, mode: str) -> str:
    text = str(label_raw).strip()

    if mode == "raw":
        return normalize_label(text)

    if mode == "yolo_coco80":
        if text.isdigit():
            idx = int(text)
            if 0 <= idx < len(COCO80):
                return normalize_label(COCO80[idx])
        return normalize_label(text)

    # auto
    if text.isdigit():
        idx = int(text)
        if 0 <= idx < len(COCO80):
            return normalize_label(COCO80[idx])
    return normalize_label(text)


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area

    if union <= 0.0:
        return 0.0
    return inter_area / union


def compute_ap(recalls, precisions):
    mrec = np.concatenate(([0.0], recalls, [1.0]))
    mpre = np.concatenate(([0.0], precisions, [0.0]))

    for i in range(len(mpre) - 1, 0, -1):
        mpre[i - 1] = max(mpre[i - 1], mpre[i])

    idx = np.where(mrec[1:] != mrec[:-1])[0]
    ap = np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1])
    return float(ap)


def evaluate_class(gt_df, pred_df, class_name: str, iou_threshold: float):
    gt_cls = gt_df[gt_df["label_norm"] == class_name].copy()
    pred_cls = pred_df[pred_df["label_norm"] == class_name].copy().sort_values(
        "score", ascending=False
    )

    gt_by_frame = {}
    for i, row in gt_cls.iterrows():
        gt_by_frame.setdefault(row["frame_key"], []).append(
            {
                "gt_index": i,
                "bbox": np.array([row["x1"], row["y1"], row["x2"], row["y2"]], dtype=float),
                "matched": False,
            }
        )

    tp = []
    fp = []

    for _, row in pred_cls.iterrows():
        frame_key = row["frame_key"]
        pred_box = np.array([row["x1"], row["y1"], row["x2"], row["y2"]], dtype=float)

        best_iou = -1.0
        best_gt = None

        for gt_item in gt_by_frame.get(frame_key, []):
            if gt_item["matched"]:
                continue
            value = iou_xyxy(pred_box, gt_item["bbox"])
            if value > best_iou:
                best_iou = value
                best_gt = gt_item

        if best_gt is not None and best_iou >= iou_threshold:
            best_gt["matched"] = True
            tp.append(1)
            fp.append(0)
        else:
            tp.append(0)
            fp.append(1)

    tp = np.array(tp, dtype=float)
    fp = np.array(fp, dtype=float)

    cum_tp = np.cumsum(tp)
    cum_fp = np.cumsum(fp)

    total_gt = len(gt_cls)
    recalls = cum_tp / total_gt if total_gt > 0 else np.array([])
    precisions = cum_tp / np.maximum(cum_tp + cum_fp, 1e-9) if len(cum_tp) > 0 else np.array([])

    ap50 = compute_ap(recalls, precisions) if total_gt > 0 and len(recalls) > 0 else np.nan

    final_tp = int(cum_tp[-1]) if len(cum_tp) > 0 else 0
    final_fp = int(cum_fp[-1]) if len(cum_fp) > 0 else 0
    final_fn = int(total_gt - final_tp)

    precision = final_tp / max(final_tp + final_fp, 1)
    recall = final_tp / max(final_tp + final_fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    return {
        "class": class_name,
        "gt_count": total_gt,
        "pred_count": int(len(pred_cls)),
        "tp": final_tp,
        "fp": final_fp,
        "fn": final_fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "ap50": ap50,
    }


def main():
    args = parse_args()

    gt_df = pd.read_csv(args.gt_csv)
    pred_df = pd.read_csv(args.pred_csv)

    required_gt = {"frame_key", "label", "x1", "y1", "x2", "y2"}
    required_pred = {"frame_key", "label_raw", "score", "x1", "y1", "x2", "y2"}

    if not required_gt.issubset(gt_df.columns):
        raise ValueError(f"GT CSV must contain columns: {sorted(required_gt)}")
    if not required_pred.issubset(pred_df.columns):
        raise ValueError(f"PRED CSV must contain columns: {sorted(required_pred)}")

    gt_df = gt_df.copy()
    gt_df["label_norm"] = gt_df["label"].map(normalize_label)

    pred_df = pred_df.copy()
    pred_df = pred_df[pred_df["is_empty"].fillna(0) == 0].copy()
    pred_df["label_norm"] = pred_df["label_raw"].map(lambda x: decode_pred_label(x, args.pred_label_mode))
    pred_df["score"] = pred_df["score"].astype(float)

    if args.classes.strip():
        selected_classes = [normalize_label(c) for c in args.classes.split(",") if c.strip()]
    else:
        selected_classes = sorted(gt_df["label_norm"].dropna().unique().tolist())

    rows = []
    for class_name in selected_classes:
        rows.append(evaluate_class(gt_df, pred_df, class_name, args.iou_threshold))

    result_df = pd.DataFrame(rows)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(output_path, index=False)

    valid_ap = result_df["ap50"].dropna()
    macro_map50 = float(valid_ap.mean()) if len(valid_ap) > 0 else float("nan")
    macro_f1 = float(result_df["f1"].mean()) if len(result_df) > 0 else float("nan")

    total_tp = int(result_df["tp"].sum()) if len(result_df) > 0 else 0
    total_fp = int(result_df["fp"].sum()) if len(result_df) > 0 else 0
    total_fn = int(result_df["fn"].sum()) if len(result_df) > 0 else 0

    micro_precision = total_tp / max(total_tp + total_fp, 1)
    micro_recall = total_tp / max(total_tp + total_fn, 1)
    micro_f1 = 2 * micro_precision * micro_recall / max(micro_precision + micro_recall, 1e-9)

    print("\nPer-class results:")
    print(result_df.to_markdown(index=False))

    print("\nSummary:")
    print(f"mAP@0.5 (macro): {macro_map50:.4f}")
    print(f"Macro F1:        {macro_f1:.4f}")
    print(f"Micro Precision: {micro_precision:.4f}")
    print(f"Micro Recall:    {micro_recall:.4f}")
    print(f"Micro F1:        {micro_f1:.4f}")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()