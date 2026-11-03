#!/usr/bin/env bash
# Refresh offline faceplate artwork.
#
# 1. Device-type YAML for Cisco, Fortinet and Palo Alto (existing snapshot script).
# 2. Official Visio stencils, converted to one SVG per front/rear panel.
# 3. NetBox device-type elevation photos, used when a stencil has no panel.
# 4. ui/public/faceplates/index.json and models/*.json (hotspots included).
#
# Cisco's stencil listing returns HTTP 403 from some networks. The script then
# uses the Internet Archive copy of the same cisco.com URL and records anything
# that could not be fetched in ui/public/faceplates/visio/SOURCES.md.
#
# Requires: git, python3, unzip, curl, emf2svg-conv, vss2raw, vss2xhtml, rsvg-convert.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMMIT="${1:-6a2703f}"
OUT="ui/public/faceplates"
VISIO="$OUT/visio"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

note() { printf '%s\n' "$*"; }

mkdir -p "$VISIO/cisco" "$VISIO/fortinet" "$VISIO/palo-alto" "$VISIO/meraki" "$OUT/library" "$OUT/vendor"

note "device-type YAML (Cisco, Fortinet, Palo Alto Networks)"
if [[ -x "$ROOT/scripts/refresh-device-types.sh" ]]; then
  "$ROOT/scripts/refresh-device-types.sh" "$COMMIT" || note "YAML refresh failed; keeping the snapshot already in the tree"
fi

# Official stencil packs. Cisco URLs are the files linked from
# https://www.cisco.com/c/en/us/products/visio-stencil-listing.html
declare -a CISCO_PACKS=(
  "2960|https://www.cisco.com/c/dam/assets/prod/visio/visio/products_visio_icon0900aecd80395a84.zip|cisco"
  "9000|https://www.cisco.com/c/dam/assets/prod/visio/visio/switches-catalyst-9000.zip|cisco"
  "wireless|https://www.cisco.com/c/dam/assets/prod/visio/visio/wireless.zip|cisco"
  "isr4000|https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-isr-4000.zip|cisco"
  "isr1100|https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-isr-1100.zip|cisco"
  "c8300|https://www.cisco.com/c/dam/assets/prod/visio/visio/catalyst-8300-v2.zip|cisco"
  "c8500|https://www.cisco.com/c/dam/assets/prod/visio/visio/catalyst-8500.zip|cisco"
  "c8000|https://www.cisco.com/c/dam/assets/prod/visio/visio/routers-catalyst-8000.zip|cisco"
  "meraki|https://www.cisco.com/c/dam/assets/prod/visio/visio/security-cisco-meraki.zip|meraki"
)
BLOCKED="$WORKDIR/blocked.txt"
: > "$BLOCKED"

fetch_zip() {
  local name="$1" url="$2" dest="$3"
  if curl -fsSL -A 'Mozilla/5.0' -o "$dest" "$url" && file "$dest" | grep -q 'Zip archive'; then
    return 0
  fi
  local raw
  if raw="$(python3 - "$url" << 'PY'
import json, sys, urllib.request
page = "https://archive.org/wayback/available?url=" + sys.argv[1]
with urllib.request.urlopen(page, timeout=40) as response:
    snap = ((json.load(response).get("archived_snapshots") or {}).get("closest") or {})
play = snap.get("url") or ""
if "/web/" not in play:
    sys.exit(1)
prefix, rest = play.split("/web/", 1)
timestamp, original = rest.split("/", 1)
print(f"{prefix}/web/{timestamp}id_/{original}")
PY
)"; then
    if curl -fL --retry 2 -A 'Mozilla/5.0' -o "$dest" "$raw" && file "$dest" | grep -q 'Zip archive'; then
      return 0
    fi
  fi
  echo "$name $url" >> "$BLOCKED"
  return 1
}

note "Fortinet Visio stencil"
curl -fL -A 'Mozilla/5.0' -o "$WORKDIR/fortinet.zip" \
  "https://www.fortinet.com/content/dam/fortinet/assets/downloads/Fortinet%20Visio%20Stencil.zip"
unzip -q -o "$WORKDIR/fortinet.zip" -d "$WORKDIR/fortinet"
shopt -s nullglob
for stencil in "$WORKDIR"/fortinet/*.vssx; do
  case "$(basename "$stencil")" in
    *Icons*) continue ;;
  esac
  python3 "$ROOT/scripts/faceplates/extract_stencils.py" --out "$ROOT/$VISIO" --vendor fortinet "$stencil"
done

note "Palo Alto Networks Visio stencil"
curl -fL -A 'Mozilla/5.0' -o "$WORKDIR/panw.vssx" \
  "https://www.paloaltonetworks.com/content/dam/pan/en_US/assets/pdf/corporate/panw-vssx.vssx"
python3 "$ROOT/scripts/faceplates/extract_stencils.py" --out "$ROOT/$VISIO" --vendor palo-alto "$WORKDIR/panw.vssx"

note "Cisco and Meraki Visio stencils"
for spec in "${CISCO_PACKS[@]}"; do
  IFS='|' read -r name url vendor <<< "$spec"
  dest="$WORKDIR/${name}.zip"
  if fetch_zip "$name" "$url" "$dest"; then
    unzip -q -o "$dest" -d "$WORKDIR/$name"
    mapfile -t stencils < <(find "$WORKDIR/$name" -type f \( -name '*.vssx' -o -name '*.vss' \))
    if ((${#stencils[@]})); then
      python3 "$ROOT/scripts/faceplates/extract_stencils.py" --out "$ROOT/$VISIO" --vendor "$vendor" "${stencils[@]}"
    fi
  else
    note "blocked: $url"
  fi
done

note "elevation photos from the device-type library"
PHOTO="$WORKDIR/photos"
mkdir -p "$PHOTO"
if git clone --filter=blob:none --sparse --depth 1 "https://github.com/netbox-community/devicetype-library.git" "$PHOTO/src"; then
  git -C "$PHOTO/src" sparse-checkout set "elevation-images/Cisco" "elevation-images/Fortinet" "elevation-images/Palo Alto Networks"
  git -C "$PHOTO/src" checkout
  python3 - "$PHOTO/src/elevation-images" "$ROOT/$OUT/library" << 'PY'
import shutil, sys
from pathlib import Path
src, dest = Path(sys.argv[1]), Path(sys.argv[2])
mapping = {"Cisco": "cisco", "Fortinet": "fortinet", "Palo Alto Networks": "palo-alto"}
for folder, vendor in mapping.items():
    origin = src / folder
    if not origin.exists():
        continue
    target = dest / vendor
    target.mkdir(parents=True, exist_ok=True)
    for path in origin.iterdir():
        if path.suffix.lower() == ".png" and (path.name.endswith(".front.png") or path.name.endswith(".rear.png")):
            shutil.copy2(path, target / path.name)
PY
  cp "$PHOTO/src/LICENSE.txt" "$ROOT/$OUT/library/LICENSE.txt" 2>/dev/null || true
fi

python3 "$ROOT/scripts/faceplates/build_catalog.py" | tee "$OUT/coverage.json"

python3 - "$BLOCKED" "$ROOT/$VISIO/SOURCES.md" << 'PY'
import sys
from pathlib import Path
blocked = Path(sys.argv[1]).read_text().strip().splitlines()
lines = [
    "# Visio faceplate sources",
    "",
    "Front-panel SVGs were converted from the vendors' official Visio stencils.",
    "Cisco's listing (https://www.cisco.com/c/en/us/products/visio-stencil-listing.html) answers HTTP 403 Access Denied from this environment, so those packs were taken from the Internet Archive snapshot of the same cisco.com URL when one existed.",
    "",
    "## Downloaded directly",
    "",
    "- Fortinet Document Library stencil zip: https://www.fortinet.com/content/dam/fortinet/assets/downloads/Fortinet%20Visio%20Stencil.zip",
    "- Palo Alto Networks press kit: https://www.paloaltonetworks.com/content/dam/pan/en_US/assets/pdf/corporate/panw-vssx.vssx",
    "- Palo Alto Networks press kit (binary .vss, not required when the .vssx converts): https://www.paloaltonetworks.com/content/dam/pan/en_US/assets/pdf/corporate/panw-vss.vss",
    "",
    "## Cisco packs",
    "",
    "Listing page: https://www.cisco.com/c/en/us/products/visio-stencil-listing.html (HTTP 403 here).",
    "Meraki collateral https://meraki.cisco.com/product-collateral/cisco-meraki-visio-stencils/?file also returns HTTP 403. The Meraki shapes in this tree come from the Security-Cisco Meraki zip on the Cisco stencil listing (December 2019). That pack does not include later MX95/MX105 faceplates.",
    "",
    "## Could not fetch",
    "",
]
if blocked:
    lines.extend(f"- {line}" for line in blocked)
else:
    lines.append("- none")
lines += [
    "",
    "Device-type YAML and elevation photos are from https://github.com/netbox-community/devicetype-library (CC0, see library/LICENSE.txt).",
    "Vendor product photos, when a stencil and a library photo are both missing, live in ../vendor with their own SOURCES.md.",
    "",
]
Path(sys.argv[2]).write_text("\n".join(lines) + "\n")
print("wrote", sys.argv[2])
if blocked:
    print("BLOCKED")
    print("\n".join(blocked))
PY

note "faceplate refresh finished"
