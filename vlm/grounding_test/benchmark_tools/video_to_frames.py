#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=str, required=True)
    parser.add_argument("--out-dir", type=str, required=True)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--image-ext", type=str, default="jpg")
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {args.video}")

    frame_idx = 0
    saved = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1

        if frame_idx % args.frame_step != 0:
            continue

        out_path = out_dir / f"frame_{frame_idx:06d}.{args.image_ext}"
        cv2.imwrite(str(out_path), frame)
        saved += 1

    cap.release()
    print(f"Saved {saved} frames to {out_dir}")


if __name__ == "__main__":
    main()