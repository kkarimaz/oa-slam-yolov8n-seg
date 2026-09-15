#!/usr/bin/env python3
"""Run a YOLOv8-seg model over an image sequence and export an OA-SLAM
detections.json (extends the classic bbox-only format with per-detection
segmentation polygons, consumed by ImageDetections::DetectionsFromFile).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a YOLOv8-seg checkpoint over a folder/rgb.txt of images "
        "and export a detections.json usable by OA-SLAM's DetectionsFromFile."
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path("yolov8n-seg.pt"),
        help="Ultralytics checkpoint or ONNX file (default: yolov8n-seg.pt).",
    )
    parser.add_argument(
        "--images",
        type=Path,
        required=True,
        help="Folder of images, or a rgb.txt-style file listing 'timestamp path' per line.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("detections.json"),
        help="Output JSON path (default: detections.json).",
    )
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def list_images(images_arg: Path) -> list[Path]:
    if images_arg.is_dir():
        return sorted(p for p in images_arg.iterdir() if p.suffix.lower() in IMAGE_EXTS)

    # rgb.txt-style listing: "timestamp relative/path.png" per line, '#' comments ignored
    base_dir = images_arg.parent
    paths = []
    with open(images_arg) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rel_path = line.split()[-1]
            paths.append(base_dir / rel_path)
    return paths


def main() -> int:
    args = parse_args()
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise RuntimeError(
            "Ultralytics is required. Install it with: pip install ultralytics"
        ) from error

    images = list_images(args.images)
    if not images:
        raise RuntimeError(f"No images found at {args.images}")

    model = YOLO(str(args.weights))

    frames = []
    total_detections = 0
    for img_path in images:
        result = model.predict(
            source=str(img_path),
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
            device=args.device,
            verbose=False,
        )[0]

        height, width = result.orig_shape
        boxes = result.boxes
        masks_xy = result.masks.xy if result.masks is not None else None

        detections = []
        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()
            det = {
                "category_id": int(boxes.cls[i].item()),
                "detection_score": float(boxes.conf[i].item()),
                "bbox": [x1, y1, x2, y2],
            }
            if masks_xy is not None:
                det["segmentation"] = [masks_xy[i].reshape(-1).tolist()]
            detections.append(det)

        frames.append(
            {
                "file_name": img_path.name,
                "width": int(width),
                "height": int(height),
                "detections": detections,
            }
        )
        total_detections += len(detections)

    args.output.write_text(json.dumps(frames))
    print(f"Wrote {len(frames)} frames / {total_detections} detections to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
