#!/usr/bin/env python3
"""Turn vendor Visio stencils into one SVG per front or rear panel.

.vssx masters are Office Open XML. The faceplate art is an embedded EMF and
the port connection points are Visio Control rows (fractions of the panel).
.vss masters are the older binary stencil. libvisio (vss2raw / vss2xhtml)
names each master and exposes the same EMF, which emf2svg-conv turns into
paths so the browser can draw it sharply.

Cisco's stencil listing (cisco.com) answers 403 from this environment. The
update script falls back to the Internet Archive copy of the same official URL.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

SKIP_PROMPT = re.compile(r"reposition|equipment label|^label$|show equipment", re.I)
VIEW_RE = re.compile(r"\b(front|rear)\b", re.I)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def slugify(name: str) -> str:
    name = name.replace("+", "-plus-")
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return name or "shape"


def view_of(name: str) -> str:
    match = VIEW_RE.search(name)
    if match and match.group(1).lower() == "rear":
        return "rear"
    return "front"


def panel_key(name: str) -> str:
    base = VIEW_RE.sub("", name)
    base = re.sub(r"\s+", " ", base).strip(" -/")
    return slugify(base)


def parse_svg_size(svg_text: str) -> tuple[float, float]:
    match = re.search(r"<svg\b[^>]*>", svg_text)
    head = match.group(0) if match else ""
    width = re.search(r'\bwidth="([0-9.]+)', head)
    height = re.search(r'\bheight="([0-9.]+)', head)
    if not width or not height:
        box = re.search(r'viewBox="[0-9.\-]+\s+[0-9.\-]+\s+([0-9.]+)\s+([0-9.]+)"', head)
        if not box:
            return 0, 0
        return float(box.group(1)), float(box.group(2))
    return float(width.group(1)), float(height.group(1))


def emf_to_svg(emf: bytes, dest: Path) -> tuple[float, float] | None:
    if shutil.which("emf2svg-conv") is None:
        raise SystemExit("emf2svg-conv is required (package emf2svg)")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "panel.emf"
        out = Path(tmp) / "panel.svg"
        src.write_bytes(emf)
        proc = subprocess.run(
            ["emf2svg-conv", "-i", str(src), "-o", str(out)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not out.exists():
            return None
        text = out.read_text(encoding="utf-8", errors="ignore")
    width, height = parse_svg_size(text)
    if width < 240 or height <= 0 or width / height < 3:
        return None
    if 'viewBox="' not in text.split(">", 1)[0]:
        text = text.replace(
            "<svg ",
            f'<svg viewBox="0 0 {width:.4f} {height:.4f}" ',
            1,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return width, height


def hotspots_from_controls(shape: ET.Element) -> list[dict]:
    """Connection points are often a port centre, or the left and right edges.

    The missing axis is filled in later, once the drawing's pixel size is known.
    """
    width = height = None
    for cell in shape:
        if local(cell.tag) != "Cell":
            continue
        if cell.get("N") == "Width":
            width = float(cell.get("V") or 0)
        elif cell.get("N") == "Height":
            height = float(cell.get("V") or 0)
    if not width or not height:
        return []
    grouped: dict[str, list[tuple[float, float]]] = {}
    for section in shape:
        if local(section.tag) != "Section" or section.get("N") != "Control":
            continue
        for row in section:
            if local(row.tag) != "Row":
                continue
            vals = {c.get("N"): c.get("V") for c in row if local(c.tag) == "Cell"}
            prompt = (vals.get("Prompt") or "").strip()
            if not prompt or SKIP_PROMPT.search(prompt):
                continue
            try:
                grouped.setdefault(prompt, []).append((float(vals["X"]), float(vals["Y"])))
            except (KeyError, TypeError, ValueError):
                continue
    raw = []
    for prompt, points in grouped.items():
        xs = [p[0] / width for p in points]
        ys = [1 - (p[1] / height) for p in points]
        raw.append({
            "prompt": prompt,
            "cx": (min(xs) + max(xs)) / 2,
            "cy": (min(ys) + max(ys)) / 2,
            "spanX": max(xs) - min(xs),
            "spanY": max(ys) - min(ys),
        })
    raw.sort(key=lambda item: (item["cx"], item["cy"]))
    return raw


def fit_hotspots(raw: list[dict], pixel_w: float, pixel_h: float) -> list[dict]:
    """Give a centre or a single measured edge a port-sized rectangle."""
    default_w = max(16.0, min(pixel_w * 0.02, 28.0)) / pixel_w
    default_h = max(18.0, min(pixel_h * 0.36, 38.0)) / pixel_h
    fitted = []
    for item in raw:
        width = item["spanX"] if item["spanX"] >= 0.012 else default_w
        height = item["spanY"] if item["spanY"] >= 0.08 else default_h
        if item["spanX"] >= 0.012:
            width = min(0.12, item["spanX"] * 1.15)
        fitted.append({
            "prompt": item["prompt"],
            "x": round(max(0.0, item["cx"] - width / 2), 5),
            "y": round(max(0.0, item["cy"] - height / 2), 5),
            "w": round(min(1.0, width), 5),
            "h": round(min(1.0, height), 5),
        })
    return fitted


def shape_with_controls(root: ET.Element) -> ET.Element | None:
    best = None
    best_n = 0
    for el in root.iter():
        if local(el.tag) != "Shape":
            continue
        count = 0
        for section in el:
            if local(section.tag) == "Section" and section.get("N") == "Control":
                count += sum(1 for row in section if local(row.tag) == "Row")
        if count > best_n:
            best, best_n = el, count
    return best


def foreign_emf(master_xml: Path, master_dir: Path) -> bytes | None:
    root = ET.parse(master_xml).getroot()
    rels_path = master_xml.parent / "_rels" / (master_xml.name + ".rels")
    rels = {}
    if rels_path.exists():
        rel_root = ET.parse(rels_path).getroot()
        for rel in rel_root:
            if local(rel.tag) == "Relationship":
                rels[rel.get("Id")] = rel.get("Target")
    for el in root.iter():
        if local(el.tag) != "ForeignData":
            continue
        rel = None
        for child in el:
            if local(child.tag) == "Rel":
                rel = child.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rels.get(rel or "")
        if not target:
            continue
        media = (master_xml.parent / target).resolve()
        if media.exists():
            return media.read_bytes()
    return None


def iter_vssx(vssx: Path):
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(vssx) as archive:
            archive.extractall(tmp)
        masters_xml = Path(tmp) / "visio" / "masters" / "masters.xml"
        if not masters_xml.exists():
            return
        root = ET.parse(masters_xml).getroot()
        rels_root = ET.parse(masters_xml.parent / "_rels" / "masters.xml.rels").getroot()
        rels = {}
        for rel in rels_root:
            if local(rel.tag) == "Relationship":
                rels[rel.get("Id")] = rel.get("Target")
        for master in root:
            if local(master.tag) != "Master":
                continue
            name = master.get("Name") or master.get("NameU") or ""
            rel_id = None
            for child in master:
                if local(child.tag) == "Rel":
                    rel_id = child.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rels.get(rel_id or "")
            if not name or not target:
                continue
            master_xml = (masters_xml.parent / target).resolve()
            if not master_xml.exists():
                continue
            emf = foreign_emf(master_xml, masters_xml.parent)
            controls = shape_with_controls(ET.parse(master_xml).getroot())
            prompts = hotspots_from_controls(controls) if controls is not None else []
            if emf:
                yield name, emf, prompts


def vss_named_emfs(vss: Path):
    if shutil.which("vss2raw") is None or shutil.which("vss2xhtml") is None:
        raise SystemExit("vss2raw and vss2xhtml are required (package libvisio-tools)")
    raw = subprocess.run(["vss2raw", str(vss)], capture_output=True)
    text = raw.stdout.decode("utf-8", errors="ignore")
    pages = re.findall(
        r"startPage\(draw:name: (.*?), svg:height: [0-9.]+in, svg:width: [0-9.]+in\)",
        text,
    )
    html = subprocess.run(["vss2xhtml", str(vss)], capture_output=True).stdout.decode("utf-8", errors="ignore")
    chunks = html.split("<svg:svg")[1:]
    emfs = []
    for chunk in chunks:
        match = re.search(r"data:image/emf;base64,([A-Za-z0-9+/=]+)", chunk)
        emfs.append(base64.b64decode(match.group(1)) if match else None)
    if len(pages) != len(emfs):
        print(f"warn: {vss.name} has {len(pages)} names and {len(emfs)} drawings", file=sys.stderr)
    for name, emf in zip(pages, emfs):
        if emf:
            yield name.strip(), emf, []


def write_panel(vendor: str, name: str, emf: bytes, prompts: list[dict], out_root: Path, manifest: list[dict]) -> None:
    key = panel_key(name)
    view = view_of(name)
    dest = out_root / vendor / f"{key}.{view}.svg"
    sidecar = dest.with_suffix(".json")
    if sidecar.exists():
        previous = json.loads(sidecar.read_text(encoding="utf-8"))
        if len(previous.get("hotspots") or []) > len(prompts):
            return
    size = emf_to_svg(emf, dest)
    if size is None:
        return
    width, height = size
    payload = {
        "name": name.strip(),
        "vendor": vendor,
        "key": key,
        "view": view,
        "file": f"/faceplates/visio/{vendor}/{dest.name}",
        "width": round(width, 2),
        "height": round(height, 2),
        "hotspots": fit_hotspots(prompts, width, height),
        "source": "visio",
    }
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    manifest.append(payload)
    print(f"  {vendor}/{dest.name}  {width:.0f}x{height:.0f}  ports={len(prompts)}  {name.strip()}")


def convert_file(path: Path, vendor: str, out_root: Path, manifest: list[dict]) -> None:
    print(f"converting {path.name} -> {vendor}")
    iterator = iter_vssx(path) if path.suffix.lower() == ".vssx" else vss_named_emfs(path)
    for name, emf, prompts in iterator:
        try:
            write_panel(vendor, name, emf, prompts, out_root, manifest)
        except Exception as exc:  # keep a bad master from aborting the pack
            print(f"  skip {name!r}: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("stencils", nargs="+", type=Path)
    args = parser.parse_args()
    manifest: list[dict] = []
    for stencil in args.stencils:
        convert_file(stencil, args.vendor, args.out, manifest)
    summary = args.out / args.vendor / "_manifest.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)} panels to {args.out / args.vendor}")


if __name__ == "__main__":
    main()
