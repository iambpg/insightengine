#!/usr/bin/env python3
"""Score every photo and stencil faceplate against the cages in the picture.

Stored overlays are fractions of the natural image. A model is kept only when
those boxes overlap port cages found independently (a dark mouth with a lighter
bezel, not an LED or a vent). Models that miss the threshold are rewritten as
drawn faceplates so the UI uses the vector panel instead of a bad photo.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_catalog import drawn_ports  # noqa: E402
from cutouts import detect_cages, edge_alignment, face_passes, overlay_alignment  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "ui" / "public"
MODELS = PUBLIC / "faceplates" / "models"
REPORT = PUBLIC / "faceplates" / "alignment-report.json"
CHECKS = ROOT / "scripts" / "faceplates" / "reports"


def load_bgr(model: dict) -> np.ndarray | None:
    path = PUBLIC / str(model.get("front") or "").lstrip("/")
    if not path.exists():
        return None
    if model.get("raster"):
        image = cv2.imread(str(path))
        return image
    try:
        import cairosvg
    except ImportError:
        return None
    width = max(1, int(round(float(model.get("width") or 1000))))
    try:
        png = cairosvg.svg2png(url=str(path), output_width=width)
    except Exception:
        return None
    array = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def realign(ports: list[dict], cages: list[dict]) -> list[dict] | None:
    """Snap each name onto a nearby detected cage. Far jumps are rejected."""
    if not ports or not cages:
        return None
    used: set[int] = set()
    moved = []
    for port in ports:
        center_x = port["x"] + port["w"] / 2
        center_y = port["y"] + port["h"] / 2
        best = None
        best_distance = 1e9
        best_index = None
        for index, cage in enumerate(cages):
            if index in used:
                continue
            distance = ((center_x - cage["cx"]) / max(port["w"], 0.008)) ** 2 + ((center_y - cage["cy"]) / max(port["h"], 0.02)) ** 2
            if distance < best_distance:
                best_distance = distance
                best = cage
                best_index = index
        if best is None or best_index is None or best_distance > 1.5 ** 2:
            return None
        used.add(best_index)
        moved.append({
            "name": port["name"],
            "type": port.get("type") or "",
            "x": round(float(best["x"]), 5),
            "y": round(float(best["y"]), 5),
            "w": round(float(best["w"]), 5),
            "h": round(float(best["h"]), 5),
        })
    return moved


def as_drawn(model: dict) -> dict:
    interfaces = [{"name": port["name"], "type": port.get("type") or "", "mgmt": False} for port in model.get("ports") or []]
    model = dict(model)
    model["source"] = "drawn"
    model["front"] = ""
    model["rear"] = ""
    model["width"] = 1000
    model["height"] = 180
    model["raster"] = False
    model["ports"] = drawn_ports(interfaces)
    return model


def score_model(model: dict, image: np.ndarray) -> tuple[dict, dict, list[dict]]:
    cages = detect_cages(image)
    mouth = overlay_alignment(image, model.get("ports") or [])
    edges = edge_alignment(image, model.get("ports") or [])
    return mouth, edges, cages


def render_check(model: dict, image: np.ndarray, dest: Path) -> None:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    canvas = Image.fromarray(rgb).convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width, height = canvas.size
    for port in model.get("ports") or []:
        x = port["x"] * width
        y = port["y"] * height
        draw.rectangle(
            [x, y, x + port["w"] * width, y + port["h"] * height],
            outline=(220, 30, 30, 255),
            width=max(1, width // 800),
            fill=(220, 30, 30, 70),
        )
    merged = Image.alpha_composite(canvas, layer).convert("RGB")
    if merged.width > 1600:
        merged = merged.resize((1600, max(1, int(merged.height * 1600 / merged.width))), Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    merged.save(dest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite models that fail the cage check")
    parser.add_argument("--checks", action="store_true", help="write overlay PNGs for the sample models")
    args = parser.parse_args()

    index_path = PUBLIC / "faceplates" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    by_slug = {entry["slug"]: entry for entry in index.get("entries") or []}
    summary = defaultdict(lambda: {"pass": 0, "realigned": 0, "fallback": 0})
    rows = []
    samples = {
        "cisco-c9300-48t",
        "cisco-c9300-48p",
        "cisco-c9200-48p",
        "cisco-ws-c2960x-48ts-l",
        "fortinet-fg-100f",
        "palo-alto-networks-pa-850",
        "palo-alto-networks-pa-3220",
        "cisco-meraki-ms225-48fp",
    }

    for path in sorted(MODELS.glob("*.json")):
        model = json.loads(path.read_text(encoding="utf-8"))
        slug = model.get("slug") or path.stem
        vendor = model.get("vendor") or "other"
        if model.get("source") == "drawn" or not model.get("front") or not model.get("ports"):
            continue
        image = load_bgr(model)
        if image is None:
            summary[vendor]["fallback"] += 1
            rows.append({"slug": slug, "vendor": vendor, "result": "fallback", "reason": "unreadable", "source": model.get("source")})
            if args.write:
                updated = as_drawn(model)
                path.write_text(json.dumps(updated), encoding="utf-8")
                if slug in by_slug:
                    by_slug[slug]["source"] = "drawn"
            continue
        mouth, edges, cages = score_model(model, image)
        score = {"mouth": mouth, "edges": edges}
        if face_passes(mouth, edges):
            summary[vendor]["pass"] += 1
            rows.append({
                "slug": slug,
                "vendor": vendor,
                "result": "pass",
                "source": model.get("source"),
                "score": score,
                "ports": len(model["ports"]),
            })
            if args.checks and slug in samples:
                render_check(model, image, CHECKS / f"{slug}.png")
            continue
        moved = realign(model["ports"], cages)
        moved_mouth = overlay_alignment(image, moved) if moved else None
        moved_edges = edge_alignment(image, moved) if moved else None
        if moved and moved_mouth and moved_edges and face_passes(moved_mouth, moved_edges):
            summary[vendor]["realigned"] += 1
            rows.append({
                "slug": slug,
                "vendor": vendor,
                "result": "realigned",
                "source": model.get("source"),
                "score": {"mouth": moved_mouth, "edges": moved_edges},
                "ports": len(moved),
            })
            model["ports"] = moved
            if args.write:
                path.write_text(json.dumps(model), encoding="utf-8")
            if args.checks and slug in samples:
                render_check(model, image, CHECKS / f"{slug}.png")
            continue
        summary[vendor]["fallback"] += 1
        rows.append({
            "slug": slug,
            "vendor": vendor,
            "result": "fallback",
            "source": model.get("source"),
            "score": score,
            "detected": len(cages),
            "ports": len(model["ports"]),
        })
        if args.write:
            updated = as_drawn(model)
            path.write_text(json.dumps(updated), encoding="utf-8")
            if slug in by_slug:
                by_slug[slug]["source"] = "drawn"

    report = {
        "method": "mouth-or-edge",
        "threshold": {
            "mouth": {"medianContrast": 10, "fraction": 0.6},
            "edges": {"medianRatio": 40, "fraction": 0.75},
        },
        "summary": {
            "pass": sum(item["pass"] for item in summary.values()),
            "realigned": sum(item["realigned"] for item in summary.values()),
            "fallback": sum(item["fallback"] for item in summary.values()),
            "byVendor": summary,
        },
        "models": rows,
    }
    if args.write or args.checks:
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if args.write:
            index_path.write_text(json.dumps({"entries": list(by_slug.values())}), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"checked {len(rows)} image faceplates")


if __name__ == "__main__":
    main()
