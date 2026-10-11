"""Filter an OA-SLAM detection JSON (list of {file_name, detections:[{category_id, detection_score, bbox}]}).

Used for detection-side ablation cells (drop_categories, e.g. person = COCO id 0) and for the OA-2
confidence sweep (min_score). The image list and frame order are preserved; frames may end up with
zero detections, which OA-SLAM handles.

Usage:
  python -m oa3.filter_detections IN.json OUT.json [--min-score 0.6] [--drop-categories 0,24]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path


def filter_file(src, dst, min_score=None, drop_categories=None) -> dict:
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    drop = set(int(c) for c in (drop_categories or []))
    total = kept = 0
    frames = data if isinstance(data, list) else data.get("frames", [])
    for fr in frames:
        dets = fr.get("detections", [])
        out = []
        for d in dets:
            total += 1
            if min_score is not None and float(d.get("detection_score", d.get("score", 0.0))) < float(min_score):
                continue
            if int(d.get("category_id", -1)) in drop:
                continue
            out.append(d)
        kept += len(out)
        fr["detections"] = out
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return {"total": total, "kept": kept, "frames": len(frames)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--drop-categories", default=None, help="comma-separated COCO category ids")
    a = ap.parse_args()
    st = filter_file(a.src, a.dst, a.min_score, [int(x) for x in a.drop_categories.split(",")] if a.drop_categories else None)
    print("frames=%d detections total=%d kept=%d -> %s" % (st["frames"], st["total"], st["kept"], a.dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
