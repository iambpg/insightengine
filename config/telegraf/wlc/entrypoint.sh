#!/bin/sh
# Render NetBox WLC targets, then start Telegraf. A failed render still
# starts the process so Prometheus can scrape an empty collector.
set -eu
umask 077
out=/tmp/wlc-generated.conf
if ! python3 /usr/local/bin/render_wlc.py -o "$out"; then
  printf '%s\n' '# NetBox target render failed; no WLC inputs this start' > "$out"
fi
exec telegraf --config /etc/telegraf/telegraf.conf --config "$out" --non-strict-env-handling "$@"
