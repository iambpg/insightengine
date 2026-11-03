#!/bin/sh
# Render NetBox WLC targets, then start Telegraf. A failed render still
# starts the process so Prometheus can scrape an empty collector.
# MDT listens on shard 0 only, unless IE_WLC_MDT is set. gNMI dial-in does
# not open the dial-out port.
set -eu
umask 077
out=/tmp/wlc-generated.conf
if ! python3 /usr/local/bin/render_wlc.py -o "$out"; then
  printf '%s\n' '# NetBox target render failed; no WLC inputs this start' > "$out"
fi
transport="${IE_WLC_MDT_TRANSPORT:-grpc}"
enable="${IE_WLC_MDT:-}"
if [ -z "$enable" ]; then
  if [ "${IE_WLC_SHARD_INDEX:-0}" = "0" ]; then
    enable=1
  else
    enable=0
  fi
fi
set -- --config /etc/telegraf/telegraf.conf --config "$out"
if [ "$transport" != "gnmi" ] && [ "$enable" != "0" ]; then
  set -- "$@" --config /etc/telegraf/mdt.conf
fi
exec telegraf "$@" --non-strict-env-handling
