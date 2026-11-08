#!/usr/bin/env python3
"""Re-check saved hotspot maps against the cages in the artwork.

A model passes when its overlays cover dark connector mouths or trace a cage
outline. This does not use the detector that first wrote the boxes.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from align_models import load_bgr  # noqa: E402
from cutouts import edge_alignment, face_passes, overlay_alignment  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "ui" / "public" / "faceplates" / "models"


def main() -> None:
    summary = defaultdict(lambda: {"pass": 0, "fail": 0})
    rows = []
    for path in sorted(MODELS.glob("*.json")):
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("source") == "drawn" or not model.get("front") or not model.get("ports"):
            continue
        image = load_bgr(model)
        if image is None:
            summary[model.get("vendor") or "other"]["fail"] += 1
            rows.append({"slug": model["slug"], "vendor": model.get("vendor"), "result": "fail", "reason": "unreadable"})
            continue
        mouth = overlay_alignment(image, model["ports"])
        edges = edge_alignment(image, model["ports"])
        score = {"mouth": mouth, "edges": edges}
        ok = face_passes(mouth, edges)
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
