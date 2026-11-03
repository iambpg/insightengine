"""Port-cutout detection and an overlap check for faceplate hotspots.

Boxes are fractions of the image (x, y, w, h), the same space the SVG overlay
uses. A hotspot map is kept only when each box overlaps a port opening found
with a second threshold. Otherwise the caller draws the panel from the port
list, which lines up by construction.
"""

from __future__ import annotations

import cv2
import numpy as np

Box = tuple[float, float, float, float]


def iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _nms(boxes: list[dict], thresh: float = 0.35) -> list[dict]:
    ordered = sorted(boxes, key=lambda item: item["w"] * item["h"], reverse=True)
    kept: list[dict] = []
    for box in ordered:
        if all(iou(box, other) < thresh for other in kept):
            kept.append(box)
    return kept


def _contours(gray: np.ndarray, dark: bool, thresh: int) -> list[dict]:
    height, width = gray.shape
    mask = (gray < thresh) if dark else (gray > thresh)
    mask = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area_img = float(width * height)
    found = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if area < area_img * 0.00028 or area > area_img * 0.02:
            continue
        if bw < width * 0.008 or bh < height * 0.045:
            continue
        if x < width * 0.025 or x + bw > width * 0.975:
            continue
        aspect = bw / max(1, bh)
        if not 0.35 <= aspect <= 2.8:
            continue
        if area / max(1, bw * bh) < 0.4:
            continue
        found.append({
            "x": x / width,
            "y": y / height,
            "w": bw / width,
            "h": bh / height,
            "cx": (x + bw / 2) / width,
            "cy": (y + bh / 2) / height,
        })
    return found


def _scan_boxes(gray: np.ndarray, dark: bool, thresh: int) -> list[dict]:
    """Track horizontal runs down the image so touching port holes stay separate."""
    height, width = gray.shape
    active: list[dict] = []
    finished: list[dict] = []

    def close(box: dict) -> None:
        bw = box["x1"] - box["x0"]
        bh = box["y1"] - box["y0"]
        if bw < width * 0.012 or bh < height * 0.05:
            return
        if bw > width * 0.08 or bh > height * 0.55:
            return
        if box["x0"] < width * 0.03 or box["x1"] > width * 0.97:
            return
        aspect = bw / max(1, bh)
        if not 0.35 <= aspect <= 2.8:
            return
        finished.append({
            "x": box["x0"] / width,
            "y": box["y0"] / height,
            "w": bw / width,
            "h": bh / height,
            "cx": (box["x0"] + bw / 2) / width,
            "cy": (box["y0"] + bh / 2) / height,
        })

    for y in range(height):
        row = gray[y]
        runs = []
        x = 0
        while x < width:
            pixel = row[x] < thresh if dark else row[x] > thresh
            if pixel:
                start = x
                while x < width and (row[x] < thresh if dark else row[x] > thresh):
                    x += 1
                if width * 0.012 <= x - start <= width * 0.08:
                    runs.append((start, x))
            else:
                x += 1
        used = set()
        next_active = []
        for start, end in runs:
            match = None
            for index, box in enumerate(active):
                if index in used:
                    continue
                overlap = min(end, box["x1"]) - max(start, box["x0"])
                if overlap > 0.5 * min(end - start, box["x1"] - box["x0"]):
                    match = index
                    break
            if match is None:
                next_active.append({"x0": start, "x1": end, "y0": y, "y1": y + 1})
                continue
            used.add(match)
            box = active[match]
            box["x0"] = min(box["x0"], start)
            box["x1"] = max(box["x1"], end)
            box["y1"] = y + 1
            next_active.append(box)
        for index, box in enumerate(active):
            if index not in used:
                close(box)
        active = next_active
    for box in active:
        close(box)
    return finished


def detect_cutouts(image_bgr: np.ndarray) -> list[dict]:
    """Every port-like opening, in image fractions, after overlap suppression."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    boxes: list[dict] = []
    for thresh in (50, 70, 90, 110):
        boxes.extend(_contours(gray, True, thresh))
    for thresh in (145, 165, 185):
        boxes.extend(_contours(gray, False, thresh))
    # A single port is a small fraction of a chassis. Wider boxes are screens and handles.
    return [box for box in _nms(boxes, 0.4) if box["w"] <= 0.075 and box["h"] <= 0.5]


def _rows(boxes: list[dict]) -> list[list[dict]]:
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda item: item["cy"])
    rows: list[list[dict]] = []
    for box in ordered:
        if rows and abs(box["cy"] - rows[-1][0]["cy"]) < 0.07:
            rows[-1].append(box)
        else:
            rows.append([box])
    split: list[list[dict]] = []
    for row in rows:
        row.sort(key=lambda item: item["cx"])
        if len(row) < 3:
            split.append(row)
            continue
        pitches = [row[i + 1]["cx"] - row[i]["cx"] for i in range(len(row) - 1)]
        typical = sorted(pitches)[len(pitches) // 2] or 0.02
        group = [row[0]]
        for index, box in enumerate(row[1:], start=1):
            if pitches[index - 1] > typical * 1.8 and len(group) >= 2:
                split.append(group)
                group = []
            group.append(box)
        if group:
            split.append(group)
    return split


def _regular(row: list[dict]) -> bool:
    if len(row) < 2:
        return False
    widths = [item["w"] for item in row]
    middle = sorted(widths)[len(widths) // 2] or 1
    if sum(abs(item - middle) for item in widths) / len(widths) / middle > 0.45:
        return False
    if len(row) >= 3:
        pitches = [row[i + 1]["cx"] - row[i]["cx"] for i in range(len(row) - 1)]
        pitch = sorted(pitches)[len(pitches) // 2] or 1
        if sum(abs(item - pitch) for item in pitches) / len(pitches) / pitch > 0.55:
            return False
    return True


def select_port_rows(cutouts: list[dict], per_row: int) -> list[dict]:
    """Keep the regular rows whose counts match the interface layout."""
    rows = [row for row in _rows(cutouts) if len(row) >= 2 and _regular(row)]
    rows = [row for row in rows if not (row[0]["cy"] < 0.45 and len(row) >= 30)]
    merged: list[list[dict]] = []
    for row in sorted(rows, key=lambda item: (item[0]["cy"], item[0]["cx"])):
        if merged and abs(row[0]["cy"] - merged[-1][0]["cy"]) < 0.04:
            merged[-1].extend(row)
            merged[-1].sort(key=lambda item: item["cx"])
        else:
            merged.append(list(row))
    rows = [row for row in merged if _regular(row) or len(row) >= per_row - 2]
    if not rows:
        return []
    target = max(1, per_row)
    pair = None
    pair_score = 10**9
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if abs(left[0]["cy"] - right[0]["cy"]) < 0.08:
                continue
            if abs(len(left) - len(right)) > max(3, min(len(left), len(right)) * 0.25):
                continue
            score = abs(len(left) - target) + abs(len(right) - target)
            if score < pair_score:
                pair_score = score
                pair = [left, right]
    if pair is not None and pair_score <= max(8, target):
        chosen = sorted(pair, key=lambda row: row[0]["cy"])
    else:
        rows.sort(key=lambda row: (abs(len(row) - target), -len(row)))
        chosen = [rows[0]]
    return [box for row in chosen for box in row]


def alignment_score(hotspots: list[dict], cutouts: list[dict]) -> dict:
    if not hotspots:
        return {"median": 0.0, "fraction": 0.0, "count": 0}
    scores = []
    for hotspot in hotspots:
        best = 0.0
        for cutout in cutouts:
            best = max(best, iou(hotspot, cutout))
        scores.append(best)
    ordered = sorted(scores)
    median = ordered[len(ordered) // 2]
    fraction = sum(score >= 0.35 for score in scores) / len(scores)
    return {"median": round(median, 3), "fraction": round(fraction, 3), "count": len(scores)}


def passes(score: dict) -> bool:
    return score["count"] > 0 and score["median"] >= 0.3 and score["fraction"] >= 0.6


def alternate_cutouts(image_bgr: np.ndarray) -> list[dict]:
    """A second threshold set so the check is not the same mask as the boxes."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    boxes: list[dict] = []
    for thresh in (40, 95, 125):
        boxes.extend(_contours(gray, True, thresh))
    for thresh in (130, 200):
        boxes.extend(_contours(gray, False, thresh))
    return _nms(boxes, 0.45)


def _is_copper(port_type: str) -> bool:
    text = (port_type or "").lower()
    return text.endswith("base-t") or text.endswith("base-tx")


def _is_optic(port_type: str) -> bool:
    text = (port_type or "").lower()
    return "sfp" in text or "qsfp" in text or text.endswith("base-x")


def label_ports(boxes: list[dict], interfaces: list[dict]) -> list[dict]:
    """Odd ports on the top row, even ports on the bottom, uplinks to the right."""
    if not boxes:
        return []
    rows: list[list[dict]] = []
    for box in sorted(boxes, key=lambda item: item["cy"]):
        if rows and abs(box["cy"] - rows[-1][0]["cy"]) < 0.08:
            rows[-1].append(box)
        else:
            rows.append([box])
    for row in rows:
        row.sort(key=lambda item: item["cx"])
    copper = [item for item in interfaces if _is_copper(item["type"]) and not item.get("mgmt")]
    optics = [item for item in interfaces if _is_optic(item["type"])]
    other = [item for item in interfaces if item not in copper and item not in optics and not item.get("mgmt")]
    ports = []
    if len(rows) >= 2 and copper and abs(len(rows[0]) - len(rows[1])) <= 4:
        top, bottom = rows[0], rows[1]
        count = min(len(top), len(bottom), len(copper) // 2 or len(copper))
        for box, iface in zip(top[:count], copper[0::2]):
            ports.append({**_geom(box), "name": iface["name"], "type": iface["type"]})
        for box, iface in zip(bottom[:count], copper[1::2]):
            ports.append({**_geom(box), "name": iface["name"], "type": iface["type"]})
        extra = top[count:] + bottom[count:]
        for box, iface in zip(extra, optics + other):
            ports.append({**_geom(box), "name": iface["name"], "type": iface["type"]})
        return ports
    flat = [box for row in rows for box in row]
    for box, iface in zip(flat, copper + optics + other):
        ports.append({**_geom(box), "name": iface["name"], "type": iface["type"]})
    return ports


def _geom(box: dict) -> dict:
    return {
        "x": round(box["x"], 5),
        "y": round(box["y"], 5),
        "w": round(box["w"], 5),
        "h": round(box["h"], 5),
    }


def per_row(interfaces: list[dict]) -> int:
    counted = [item for item in interfaces if not item.get("mgmt")]
    count = len(counted) or 1
    if count >= 8:
        return max(4, count // 2)
    return count


def choose_hotspots(image_bgr: np.ndarray, interfaces: list[dict], prompted: list[dict] | None) -> tuple[list[dict] | None, dict]:
    """Stencil points win when they sit on openings. Otherwise use the cutouts."""
    cutouts = detect_cutouts(image_bgr)
    prompted = prompted or []
    if prompted:
        prompted_score = alignment_score(prompted, cutouts)
        if passes(prompted_score):
            snapped = snap_to_cutouts(prompted, cutouts)
            # Keep the stencil names, but use the opening's box when the snap landed.
            if len(snapped) >= len(prompted) * 0.6:
                snapped_score = alignment_score(snapped, cutouts)
                if passes(snapped_score):
                    return snapped, snapped_score
            return prompted, prompted_score
    labeled = label_ports(select_port_rows(cutouts, per_row(interfaces)), interfaces)
    labeled_score = alignment_score(labeled, cutouts)
    if passes(labeled_score):
        return labeled, labeled_score
    return None, labeled_score or alignment_score(prompted, cutouts)


def snap_to_cutouts(hotspots: list[dict], cutouts: list[dict]) -> list[dict]:
    """Move each named hotspot onto the opening it actually covers."""
    used: set[int] = set()
    snapped = []
    for hotspot in hotspots:
        best_i = None
        best = 0.0
        for index, cutout in enumerate(cutouts):
            if index in used:
                continue
            score = iou(hotspot, cutout)
            if score > best:
                best = score
                best_i = index
        if best_i is None or best < 0.12:
            continue
        used.add(best_i)
        cutout = cutouts[best_i]
        snapped.append({
            "name": hotspot["name"],
            "type": hotspot.get("type") or "",
            "x": round(cutout["x"], 5),
            "y": round(cutout["y"], 5),
            "w": round(cutout["w"], 5),
            "h": round(cutout["h"], 5),
        })
    return snapped
