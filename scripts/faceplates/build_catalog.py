#!/usr/bin/env python3
"""Join device-type YAML to Visio panels and write the faceplate catalog.

Hotspots come from Visio connection points when the stencil has them.
Otherwise a dark-opening scan places a box on each physical port. Models
with no artwork get a drawn faceplate and a generated grid.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
import cv2
import numpy as np
from PIL import Image

from cutouts import alignment_score, choose_hotspots

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "netbox" / "device-types" / "library" / "device-types"
VISIO = ROOT / "ui" / "public" / "faceplates" / "visio"
PUBLIC = ROOT / "ui" / "public" / "faceplates"
VENDOR_DIRS = {
    "Cisco": "cisco",
    "Fortinet": "fortinet",
    "Palo Alto Networks": "palo-alto",
}

SKIP_IFACE = re.compile(r"stackwise|lag|bridge|virtual|tunnel", re.I)
SKIP_PROMPT = re.compile(r"usb|console|dc connector|power|antenna|ground", re.I)
NUM = re.compile(r"#(\d+)|\b(\d+)\b")


def norm(value: str) -> str:
    text = (value or "").lower().replace("plus", "+")
    return re.sub(r"[^a-z0-9+]+", "", text)


def expand_name(name: str) -> list[str]:
    name = re.sub(r"\b(front|rear)\b", "", name, flags=re.I).strip(" -")
    match = re.search(r"([A-Za-z0-9+]+)/([A-Za-z0-9+]+)", name)
    if not match:
        return [name] if name else []
    left, right = name[: match.start()], name[match.end() :]
    first, second = match.group(1), match.group(2)
    number_suffix = re.match(r"(\d+)([A-Za-z]*)$", first), re.match(r"(\d+)([A-Za-z]*)$", second)
    if number_suffix[0] and number_suffix[1]:
        suffix = number_suffix[0].group(2) or number_suffix[1].group(2)
        first = number_suffix[0].group(1) + suffix
        second = number_suffix[1].group(1) + suffix
    found = []
    for piece in (first, second):
        found.extend(expand_name(f"{left}{piece}{right}"))
    # preserve order, drop duplicates
    seen = set()
    unique = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def last_number(value: str) -> int | None:
    nums = re.findall(r"\d+", value or "")
    return int(nums[-1]) if nums else None


def prompt_number(prompt: str) -> int | None:
    match = re.search(r"#(\d+)", prompt or "")
    if match:
        return int(match.group(1))
    return last_number(prompt)


def load_devices() -> list[dict]:
    devices = []
    for path in sorted(LIBRARY.glob("*/*.yaml")) + sorted(LIBRARY.glob("*/*.yml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict) or not data.get("model"):
            continue
        interfaces = []
        for row in data.get("interfaces") or []:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            if SKIP_IFACE.search(str(row.get("type") or "")):
                continue
            interfaces.append({
                "name": str(row["name"]),
                "type": str(row.get("type") or ""),
                "mgmt": bool(row.get("mgmt_only")) or str(row["name"]).lower() in {"management", "mgmt"},
            })
        manufacturer = str(data.get("manufacturer") or path.parent.name)
        devices.append({
            "manufacturer": manufacturer,
            "vendor": VENDOR_DIRS.get(manufacturer, "cisco" if "meraki" in path.name.lower() else slug_vendor(manufacturer)),
            "model": str(data.get("model") or ""),
            "partNumber": str(data.get("part_number") or ""),
            "slug": str(data.get("slug") or path.stem),
            "stem": path.stem,
            "frontImage": bool(data.get("front_image")),
            "rearImage": bool(data.get("rear_image")),
            "interfaces": interfaces,
            "meraki": path.name.lower().startswith("meraki-") or "meraki" in str(data.get("model") or "").lower(),
        })
    return devices


def slug_vendor(name: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return token or "other"


def device_keys(device: dict) -> set[str]:
    keys = {norm(device["model"]), norm(device["partNumber"]), norm(device["slug"]), norm(device["stem"])}
    keys.discard("")
    expanded = set()
    for key in keys:
        expanded.add(key)
        for prefix in ("ciscocatalyst", "paloaltonetworks", "paloalto", "fortigate", "fortinet", "cisco", "meraki", "catalyst"):
            if key.startswith(prefix) and len(key) - len(prefix) >= 3:
                expanded.add(key[len(prefix):])
        if key.startswith("wsc") and len(key) > 5:
            expanded.add(key[3:])
        elif key.startswith("ws") and len(key) > 4:
            expanded.add(key[2:])
    return {key for key in expanded if len(key) >= 3}


def index_devices(devices: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for device in devices:
        for key in device_keys(device):
            index[key].append(device)
    return index


def choose_device(candidates: list[dict], alias: str) -> dict | None:
    if not candidates:
        return None
    target = norm(alias)
    exact = [item for item in candidates if target in {norm(item["partNumber"]), norm(item["model"]), norm(item["slug"]), norm(item["stem"])}]
    pool = exact or candidates
    # Prefer the part number closest in length to the alias so C9300-48P beats C9300-48P-E.
    pool = sorted(pool, key=lambda item: (abs(len(norm(item["partNumber"] or item["model"])) - len(target)), len(item["partNumber"])))
    return pool[0]


def load_visio() -> list[dict]:
    panels = []
    if not VISIO.exists():
        return panels
    for path in sorted(VISIO.glob("*/*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("view") not in (None, "front", "rear"):
            continue
        panels.append(data)
    return panels


def attach_visio(devices: list[dict], panels: list[dict]) -> dict[str, dict]:
    """slug -> {front, rear} panel records."""
    index = index_devices(devices)
    linked: dict[str, dict] = defaultdict(dict)
    for panel in panels:
        aliases = expand_name(panel.get("name") or panel.get("key") or "")
        aliases.append((panel.get("key") or "").replace("-", " "))
        matched = []
        seen = set()
        for alias in aliases:
            chosen = choose_device(index.get(norm(alias), []), alias)
            if chosen and chosen["slug"] not in seen:
                seen.add(chosen["slug"])
                matched.append(chosen)
        view = panel.get("view") or "front"
        for chosen in matched:
            current = linked[chosen["slug"]].get(view)
            if current and len(current.get("hotspots") or []) >= len(panel.get("hotspots") or []):
                continue
            linked[chosen["slug"]][view] = panel
    return linked


def rasterize(svg: Path, width: int) -> Image.Image | None:
    if shutil_which("rsvg-convert") is None or not svg.exists():
        return None
    from tempfile import NamedTemporaryFile
    import os
    with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        png = tmp.name
    proc = subprocess.run(["rsvg-convert", "-w", str(width), str(svg), "-o", png], capture_output=True)
    if proc.returncode != 0:
        os.unlink(png)
        return None
    image = Image.open(png).convert("RGB")
    image.load()
    os.unlink(png)
    return image


def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)


def rasterize_bgr(svg: Path, width: int):
    image = rasterize(svg, width)
    if image is None:
        return None
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _luminance(pixel) -> float:
    red, green, blue = pixel[:3]
    return (red + green + blue) / 3


def _runs(image: Image.Image, y: int, min_fraction: float) -> list[tuple[int, int]]:
    width, height = image.size
    pixels = image.load()
    min_w = max(8, int(width * min_fraction))
    max_w = max(min_w + 4, int(width * 0.04))
    found = []
    x = int(width * 0.02)
    limit = int(width * 0.99)
    while x < limit:
        if _luminance(pixels[x, y]) < 88:
            start = x
            while x < limit and _luminance(pixels[x, y]) < 105:
                x += 1
            if min_w <= x - start <= max_w:
                found.append((start, x - start))
        else:
            x += 1
    return found


def _groups(runs: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    if not runs:
        return []
    pitches = [runs[i + 1][0] - runs[i][0] for i in range(len(runs) - 1)]
    typical = sorted(pitches)[len(pitches) // 2] if pitches else runs[0][1]
    groups: list[list[tuple[int, int]]] = [[runs[0]]]
    for index, run in enumerate(runs[1:], start=1):
        if pitches[index - 1] > typical * 1.55 and len(groups[-1]) >= 2:
            groups.append([])
        groups[-1].append(run)
    return groups


def detect_openings(image: Image.Image, per_row: int = 24) -> list[dict]:
    """Rows of dark openings whose count matches the copper ports on one row.

    Tall chassis (firewalls) are scanned below the vent. Uplink cages that sit
    to the right of a gap are kept once, not once per row.
    """
    width, height = image.size
    tall = height / width > 0.14
    y_start = int(height * (0.45 if tall else 0.22))
    y_end = int(height * 0.9)
    row_h = 0.11 if tall else 0.2
    candidates = []
    extras_at = {}
    for y in range(y_start, y_end, 2):
        runs = _runs(image, y, 0.022 if tall else 0.012)
        if len(runs) < 4:
            continue
        groups = _groups(runs)
        matched = None
        extras = []
        for group in groups:
            if abs(len(group) - per_row) <= 1 and len(group) >= 4:
                widths = [run for _, run in group]
                middle = sorted(widths)[len(widths) // 2]
                deviation = sum(abs(item - middle) for item in widths) / len(widths)
                if matched is None or deviation < matched[0]:
                    matched = (deviation, group)
            elif 1 <= len(group) <= 8:
                extras.append(group)
        if matched:
            candidates.append((matched[0], abs(len(matched[1]) - per_row), y, matched[1]))
            extras_at[y] = extras
    if not candidates:
        return []
    candidates.sort()
    picked = []
    for _dev, _delta, y, group in candidates:
        if any(abs(y - other) < height * 0.16 for other, _group in picked):
            continue
        picked.append((y, group))
        if len(picked) == (2 if per_row >= 8 else 1):
            break
    picked.sort()
    boxes = []

    def add(start: int, run: int, y: int) -> None:
        boxes.append({
            "x": start / width,
            "y": max(0.0, y / height - row_h / 2),
            "w": run / width,
            "h": row_h,
            "cx": (start + run / 2) / width,
            "cy": y / height,
        })

    for y, group in picked:
        for start, run in group:
            add(start, run, y)
    if picked:
        for group in extras_at.get(picked[0][0], []):
            for start, run in group:
                center = (start + run / 2) / width
                if any(abs(center - box["cx"]) < 0.02 for box in boxes):
                    continue
                add(start, run, picked[0][0])
    boxes.sort(key=lambda item: (round(item["cy"], 2), item["cx"]))
    return boxes


def is_copper(port_type: str) -> bool:
    text = port_type.lower()
    return text.endswith("base-t") or text.endswith("base-tx")


def is_optic(port_type: str) -> bool:
    text = port_type.lower()
    return "sfp" in text or "qsfp" in text or text.endswith("base-x")


def per_row_for(interfaces: list[dict]) -> int:
    counted = [item for item in interfaces if not item.get("mgmt")]
    count = len(counted) or 1
    if count >= 8:
        return max(4, count // 2)
    return count


def assign_detected(boxes: list[dict], interfaces: list[dict]) -> list[dict]:
    if not boxes:
        return []
    rows: list[list[dict]] = []
    for box in boxes:
        if rows and abs(box["cy"] - rows[-1][0]["cy"]) < 0.08:
            rows[-1].append(box)
        else:
            rows.append([box])
    for row in rows:
        row.sort(key=lambda item: item["cx"])
    copper = [item for item in interfaces if is_copper(item["type"]) and not item.get("mgmt")]
    optics = [item for item in interfaces if is_optic(item["type"])]
    other = [item for item in interfaces if item not in copper and item not in optics]
    # Two equal copper rows: Cisco numbers odd ports on the top row.
    ports = []
    used = set()
    if len(rows) >= 2 and copper and abs(len(rows[0]) - len(rows[1])) <= 2 and len(copper) >= len(rows[0]) + len(rows[1]) - 2:
        top, bottom = rows[0], rows[1]
        # Drop a short right-hand group from the copper rows; those are uplinks.
        def copper_part(row):
            if len(row) > 8 and row[-1]["cx"] - row[-2]["cx"] > (row[1]["cx"] - row[0]["cx"]) * 1.7:
                return row[:-1], row[-1:]
            return row, []
        top_c, top_x = copper_part(top)
        bot_c, bot_x = copper_part(bottom)
        odds = copper[0::2]
        evens = copper[1::2]
        for box, iface in zip(top_c, odds):
            ports.append({**box, "name": iface["name"], "type": iface["type"]})
            used.add(iface["name"])
        for box, iface in zip(bot_c, evens):
            ports.append({**box, "name": iface["name"], "type": iface["type"]})
            used.add(iface["name"])
        uplink_boxes = top_x + bot_x + [box for row in rows[2:] for box in row]
    else:
        flat = [box for row in rows for box in row]
        uplink_boxes = []
        for box, iface in zip(flat, copper + optics + other):
            ports.append({**box, "name": iface["name"], "type": iface["type"]})
            used.add(iface["name"])
        return [{key: value for key, value in port.items() if key in ("name", "type", "x", "y", "w", "h")} for port in ports]
    remaining = [item for item in optics + other + copper if item["name"] not in used]
    for box, iface in zip(uplink_boxes, remaining):
        ports.append({**box, "name": iface["name"], "type": iface["type"]})
    return [{key: value for key, value in port.items() if key in ("name", "type", "x", "y", "w", "h")} for port in ports]


def assign_prompts(hotspots: list[dict], interfaces: list[dict]) -> list[dict]:
    by_number: dict[int, list[dict]] = defaultdict(list)
    for iface in interfaces:
        number = last_number(iface["name"])
        if number is not None:
            by_number[number].append(iface)
    used = set()
    assigned = []

    def take(predicate) -> dict | None:
        for iface in interfaces:
            if iface["name"] in used:
                continue
            if predicate(iface):
                used.add(iface["name"])
                return iface
        return None

    for hotspot in hotspots:
        prompt = hotspot.get("prompt") or ""
        if SKIP_PROMPT.search(prompt):
            continue
        low = prompt.lower()
        iface = None
        number = prompt_number(prompt)
        if "wan" in low:
            iface = take(lambda item: "wan" in item["name"].lower())
        elif "mgmt" in low or "management" in low:
            iface = take(lambda item: "mgmt" in item["name"].lower() or item["name"].lower() in ("management", "ma1"))
            if iface is None and number is not None:
                iface = take(lambda item, number=number: last_number(item["name"]) == number and "mgmt" in item["name"].lower())
        elif "ha" in low:
            iface = take(lambda item, number=number: item["name"].lower().startswith("ha") and (number is None or str(number) in item["name"] or item["name"].endswith(chr(ord("a") + number - 1))))
        elif number is not None:
            for candidate in by_number.get(number, []):
                if candidate["name"] not in used:
                    iface = candidate
                    used.add(candidate["name"])
                    break
        if iface is None:
            assigned.append({**hotspot, "name": prompt, "unmatched": True})
        else:
            assigned.append({**hotspot, "name": iface["name"], "type": iface["type"]})
    leftovers = [item for item in interfaces if item["name"] not in used and is_copper(item["type"])]
    open_spots = [item for item in assigned if item.get("unmatched")]
    for spot, iface in zip(sorted(open_spots, key=lambda item: item["x"]), leftovers):
        spot["name"] = iface["name"]
        spot["type"] = iface["type"]
        spot.pop("unmatched", None)
        used.add(iface["name"])
    cleaned = []
    for spot in assigned:
        if spot.get("unmatched"):
            continue
        cleaned.append({
            "name": spot["name"],
            "type": spot.get("type") or "",
            "x": spot["x"],
            "y": spot["y"],
            "w": spot["w"],
            "h": spot["h"],
        })
    return cleaned


def drawn_ports(interfaces: list[dict]) -> list[dict]:
    """A 1U-style grid. Odd ports on the top row, same as a Catalyst."""
    copper = [item for item in interfaces if is_copper(item["type"])]
    optics = [item for item in interfaces if is_optic(item["type"])]
    rows = 2 if len(copper) > 8 else 1
    ports = []
    if rows == 2:
        top = copper[0::2]
        bottom = copper[1::2]
        for index, iface in enumerate(top):
            ports.append(place(iface, index, len(top), 0.22, 0.08))
        for index, iface in enumerate(bottom):
            ports.append(place(iface, index, len(bottom), 0.58, 0.08))
        origin = 0.78
    else:
        for index, iface in enumerate(copper):
            ports.append(place(iface, index, max(1, len(copper)), 0.38, 0.08))
        origin = 0.08 + 0.84 * (len(copper) / max(1, len(copper) + len(optics)))
    for index, iface in enumerate(optics):
        ports.append({
            "name": iface["name"],
            "type": iface["type"],
            "x": round(min(0.96, origin + index * 0.045), 5),
            "y": 0.3,
            "w": 0.032,
            "h": 0.4,
        })
    return ports


def place(iface: dict, index: int, count: int, y: float, origin: float) -> dict:
    span = 0.7 if count else 0.7
    pitch = span / max(1, count)
    return {
        "name": iface["name"],
        "type": iface["type"],
        "x": round(origin + index * pitch, 5),
        "y": y,
        "w": round(min(0.04, pitch * 0.72), 5),
        "h": 0.28,
    }


def public_url(path: Path) -> str:
    relative = path.relative_to(ROOT / "ui" / "public")
    return "/" + relative.as_posix()


def build(limit_slugs: set[str] | None = None) -> dict:
    devices = load_devices()
    panels = load_visio()
    linked = attach_visio(devices, panels)
    library_root = PUBLIC / "library"
    vendor_root = PUBLIC / "vendor"
    models_dir = PUBLIC / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    counts = defaultdict(lambda: {"visio": 0, "photo": 0, "vendor": 0, "drawn": 0, "devices": 0, "aligned": 0, "fallback": 0})
    entries = []
    report = []
    for device in devices:
        if limit_slugs and device["slug"] not in limit_slugs:
            continue
        vendor = "meraki" if device["meraki"] else device["vendor"]
        bucket = counts[vendor]
        bucket["devices"] += 1
        art = linked.get(device["slug"], {})
        front = art.get("front")
        rear = art.get("rear")
        source = "drawn"
        front_url = rear_url = ""
        width = 1000
        height = 180
        raster = False
        ports: list[dict] = []
        score = {"median": 0, "fraction": 0, "count": 0}
        image_bgr = None
        prompted = None
        if front:
            source = "visio"
            front_url = front["file"]
            width = float(front["width"])
            height = float(front["height"])
            if front.get("hotspots"):
                prompted = assign_prompts(front["hotspots"], device["interfaces"])
            svg_path = ROOT / "ui" / "public" / front["file"].lstrip("/")
            image_bgr = rasterize_bgr(svg_path, max(1, int(round(width))))
            if rear:
                rear_url = rear["file"]
        else:
            photo = library_root / device["vendor"] / f"{device['slug']}.front.png"
            vendor_photo = vendor_root / vendor / f"{device['slug']}.front.png"
            chosen_photo = photo if photo.exists() else vendor_photo if vendor_photo.exists() else None
            if chosen_photo is not None:
                source = "photo" if chosen_photo == photo else "vendor"
                with Image.open(chosen_photo) as image:
                    width, height = image.size
                front_url = public_url(chosen_photo)
                raster = True
                image_bgr = cv2.cvtColor(np.array(Image.open(chosen_photo).convert("RGB")), cv2.COLOR_RGB2BGR)
        if image_bgr is not None:
            # Detection ran in the raster's pixel space. Fractions match the viewBox
            # when the raster width is the SVG width, so hotspots share that space.
            aligned, score = choose_hotspots(image_bgr, device["interfaces"], prompted)
            if aligned:
                ports = aligned
                bucket["aligned"] += 1
            else:
                report.append({
                    "slug": device["slug"],
                    "vendor": vendor,
                    "result": "fallback",
                    "attempted": source,
                    "score": score,
                })
                source = "drawn"
                front_url = ""
                rear_url = ""
                width, height = 1000, 180
                raster = False
                bucket["fallback"] += 1
                ports = drawn_ports(device["interfaces"])
        if source == "drawn" and not ports:
            ports = drawn_ports(device["interfaces"])
            width, height = 1000, 180
        if source != "drawn":
            report.append({
                "slug": device["slug"],
                "vendor": vendor,
                "result": "pass",
                "source": source,
                "score": score,
                "ports": len(ports),
            })
        bucket[source] += 1
        model = {
            "slug": device["slug"],
            "model": device["model"],
            "partNumber": device["partNumber"],
            "manufacturer": device["manufacturer"],
            "vendor": vendor,
            "source": source,
            "front": front_url,
            "rear": rear_url,
            "width": width,
            "height": height,
            "raster": raster,
            "ports": ports,
        }
        (models_dir / f"{device['slug']}.json").write_text(json.dumps(model), encoding="utf-8")
        entries.append({
            "slug": device["slug"],
            "model": device["model"],
            "partNumber": device["partNumber"],
            "manufacturer": device["manufacturer"],
            "vendor": vendor,
            "source": source,
        })
    index = {"entries": entries}
    (PUBLIC / "index.json").write_text(json.dumps(index), encoding="utf-8")
    passed = [row for row in report if row["result"] == "pass"]
    failed = [row for row in report if row["result"] == "fallback"]
    summary = defaultdict(lambda: {"pass": 0, "fallback": 0})
    for row in report:
        summary[row["vendor"]][row["result"] if row["result"] == "pass" else "fallback"] += 1
    coverage = {
        "byVendor": counts,
        "devices": len(entries),
        "alignment": {"pass": len(passed), "fallback": len(failed), "byVendor": summary},
    }
    (PUBLIC / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    (PUBLIC / "alignment-report.json").write_text(json.dumps({"summary": coverage["alignment"], "models": report}, indent=2), encoding="utf-8")
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", action="append", default=[])
    args = parser.parse_args()
    coverage = build(set(args.slug) if args.slug else None)
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()
