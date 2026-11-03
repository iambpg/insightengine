#!/bin/sh
# Render NetBox WLC targets, then start Telegraf. A failed render still
# starts the process so Prometheus can scrape an empty collector.
# MDT listens on shard 0 only, unless IE_WLC_MDT is set. gNMI dial-in does
# not open the dial-out port.
set -eu
umask 077
# The host NetBox token is often root:root mode 0600. Stage a 0400 copy for
# uid 10001, then continue this script as that user. Telegraf is not root.
if [ "$(id -u)" -eq 0 ]; then
  export IE_RUN_UID="${IE_RUN_UID:-10001}"
  export IE_RUN_GID="${IE_RUN_GID:-10001}"
  exec /usr/local/bin/drop-priv.sh /entrypoint.sh "$@"
fi
# catalog.py is copied next to render_wlc.py and is also on the /etc/telegraf
# checkout mount (compose and upgrade.sh).
export PYTHONPATH="/usr/local/bin:/etc/telegraf${PYTHONPATH:+:$PYTHONPATH}"
# Dial-out port. 57500 is where Telegraf is reached. 57400 is UI HTTPS.
IE_MDT_PORT="${IE_MDT_PORT:-57500}"
export IE_MDT_PORT
out=/tmp/wlc-generated.conf
refresh="${IE_WLC_REFRESH_SECONDS:-300}"
case "$refresh" in
  ''|*[!0-9]*) refresh=300 ;;
esac
if [ ! -s "$out" ]; then
  printf '%s\n' '# NetBox target list is not available yet' > "$out"
fi
# Retry quickly until the first good list, then every IE_WLC_REFRESH_SECONDS
# (default 5 minutes). A failed fetch does not replace the last good file.
# The dial-out Telegraf is not reloaded. Only the polling process, which
# reads this generated file, is restarted when the list changes.
poller_pid=
main_pid=
stop_poller() {
  if [ -n "$poller_pid" ]; then
    kill "$poller_pid" 2>/dev/null || true
    wait "$poller_pid" 2>/dev/null || true
    poller_pid=
  fi
}
start_poller() {
  stop_poller
  if ! grep -q '^\[\[inputs\.' "$out" 2>/dev/null; then
    return 0
  fi
  telegraf --config /etc/telegraf/poller.conf --config "$out" --non-strict-env-handling &
  poller_pid=$!
  echo "reloaded WLC poller"
}
stop_children() {
  stop_poller
  if [ -n "$main_pid" ]; then
    kill "$main_pid" 2>/dev/null || true
  fi
}
trap 'stop_children; wait; exit 0' TERM INT

transport="${IE_WLC_MDT_TRANSPORT:-grpc}"
enable="${IE_WLC_MDT:-}"
if [ -z "$enable" ]; then
  if [ "${IE_WLC_SHARD_INDEX:-0}" = "0" ]; then
    enable=1
  else
    enable=0
  fi
fi
set -- --config /etc/telegraf/telegraf.conf
if [ "$transport" != "gnmi" ] && [ "$enable" != "0" ]; then
  set -- "$@" --config /etc/telegraf/mdt.conf
fi
telegraf "$@" --non-strict-env-handling &
main_pid=$!

delay=2
have=0
while kill -0 "$main_pid" 2>/dev/null; do
  if log=$(python3 /usr/local/bin/render_wlc.py -o "$out" 2>&1); then
    printf '%s\n' "$log"
    case "$log" in
      wrote*) start_poller ;;
    esac
    have=1
    delay=2
    sleep "$refresh"
  elif [ "$have" -eq 0 ]; then
    printf '%s\n' "$log"
    sleep "$delay"
    if [ "$delay" -lt 30 ]; then
      delay=$((delay * 2))
    fi
  else
    printf '%s\n' "$log"
    sleep "$refresh"
  fi
done
wait "$main_pid"
