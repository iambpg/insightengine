#!/usr/bin/env python3
"""Re-check saved hotspot maps against port openings in the artwork.

Renders each model that still has a front image, detects cutouts independently,
and requires every hotspot to overlap an opening (IoU). A failing model is
reported; build_catalog.py already drops those maps and draws the panel instead.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_catalog import rasterize_bgr  # noqa: E402
from cutouts import alignment_score, detect_cutouts, passes  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "ui" / "public" / "faceplates" / "models"
PUBLIC = ROOT / "ui" / "public"


def main() -> None:
    summary = defaultdict(lambda: {"pass": 0, "fail": 0})
    rows = []
    for path in sorted(MODELS.glob("*.json")):
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("source") == "drawn" or not model.get("front") or not model.get("ports"):
            continue
        image_path = PUBLIC / model["front"].lstrip("/")
        if model.get("raster"):
            image = cv2.imread(str(image_path))
        else:
            image = rasterize_bgr(image_path, max(1, int(round(model["width"]))))
        if image is None:
            summary[model.get("vendor") or "other"]["fail"] += 1
            rows.append({"slug": model["slug"], "vendor": model.get("vendor"), "result": "fail", "reason": "unreadable"})
            continue
        score = alignment_score(model["ports"], detect_cutouts(image))
        ok = passes(score)
        vendor = model.get("vendor") or "other"
        summary[vendor]["pass" if ok else "fail"] += 1
        rows.append({"slug": model["slug"], "vendor": vendor, "result": "pass" if ok else "fail", "score": score})
    report = {"summary": summary, "models": rows}
    out = ROOT / "ui" / "public" / "faceplates" / "alignment-check.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    failed = [row for row in rows if row["result"] == "fail"]
    print(f"checked {len(rows)} image faceplates, {len(failed)} fail")


if __name__ == "__main__":
    main()
