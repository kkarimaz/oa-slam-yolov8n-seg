#!/usr/bin/env python3
"""Export a YOLOv8 segmentation model to ONNX for OA-SLAM OpenCV DNN."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a YOLOv8-seg checkpoint to an OpenCV-compatible ONNX file."
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path("yolov8n-seg.pt"),
        help="Input Ultralytics checkpoint (default: yolov8n-seg.pt).",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=320,
        help="Square inference size expected by OA-SLAM (default: 320).",
    )
    parser.add_argument(
        "--opset",
        type=int,
        default=12,
        help="ONNX opset version (default: 12).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the exported file (default: checkpoint directory).",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Export device, for example cpu or 0 (default: cpu).",
    )
    parser.add_argument(
        "--no-simplify",
        action="store_true",
        help="Do not simplify the exported ONNX graph.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.imgsz <= 0:
        raise ValueError("--imgsz must be greater than zero")
    if args.opset <= 0:
        raise ValueError("--opset must be greater than zero")
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError(
            "Ultralytics is required. Install it with: pip install ultralytics"
        ) from error

    model = YOLO(str(args.weights))
    export_path = model.export(
        format="onnx",
        imgsz=args.imgsz,
        opset=args.opset,
        simplify=not args.no_simplify,
        dynamic=False,
        nms=False,
        device=args.device,
        project=str(args.output_dir) if args.output_dir else None,
        name=args.weights.stem if args.output_dir else None,
    )

    print(f"Exported ONNX model: {export_path}")
    print(f"Use it with OA-SLAM as the detections_file argument: {export_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())