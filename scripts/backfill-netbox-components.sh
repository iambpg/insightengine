#!/usr/bin/env bash
# Create NetBox components that a device type defines but the device lacks.
#
#   ./scripts/backfill-netbox-components.sh
#   ./scripts/backfill-netbox-components.sh --dry-run
#
# Uses the compose service netbox-component-backfill, which reads
# secrets/prometheus/netbox.token. Build the image first if it is not local:
#   docker compose build netbox-component-backfill
# NETBOX_BACKFILL_COMPONENTS=false skips the run (the container exits 0).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec docker compose run --rm --no-deps netbox-component-backfill "$@"
