#!/usr/bin/env bash
# Replace the vendored device-type snapshot with another upstream commit.
# Only Cisco, Fortinet and Palo Alto Networks YAML is downloaded (not the
# elevation images that make a full clone about 1 GB).
#
#   ./scripts/refresh-device-types.sh
#   ./scripts/refresh-device-types.sh 6a2703f
#
# Requires git and network access. Does not start Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMMIT="${1:-6a2703f}"
DEST="netbox/device-types/library"
command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
printf '%s' "$COMMIT" | grep -Eq '^[0-9a-fA-F]{7,40}$' || { echo "commit must be a hex sha" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
echo "cloning device-type paths at ${COMMIT} (YAML only)"
git clone --filter=blob:none --sparse "https://github.com/netbox-community/devicetype-library.git" "$tmp/src"
git -C "$tmp/src" sparse-checkout set \
  "device-types/Cisco" \
  "device-types/Fortinet" \
  "device-types/Palo Alto Networks" \
  "module-types/Cisco" \
  "module-types/Fortinet" \
  "module-types/Palo Alto Networks"
git -C "$tmp/src" fetch --depth 1 origin "$COMMIT"
git -C "$tmp/src" checkout --detach FETCH_HEAD

rm -rf "$DEST/device-types" "$DEST/module-types"
mkdir -p "$DEST"
cp -a "$tmp/src/device-types" "$tmp/src/module-types" "$DEST/"
resolved="$(git -C "$tmp/src" rev-parse HEAD)"
cat > "$DEST/SOURCE" <<EOF
origin: https://github.com/netbox-community/devicetype-library
commit: ${resolved}
vendors: Cisco, Fortinet, Palo Alto Networks
contents: device-types and module-types YAML only
reason: vendored so an offline server can preload NetBox without cloning the 1 GB upstream tree
refresh: scripts/refresh-device-types.sh and docs/device-types.md
EOF
echo "updated ${DEST} to ${resolved}"
echo "rebuild the importer image: docker compose build netbox-device-types"
