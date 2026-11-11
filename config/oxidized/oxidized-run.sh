#!/bin/sh
# Oxidized exits, or never opens :8888, when NetBox returns no devices
# ("source returns no usable nodes"). A fresh install has zero devices.
# Retry Oxidized, and while it is down answer GET /nodes with [] so the
# healthcheck stays green. When a device exists, Oxidized binds the port and
# this script just waits on it.
#
# The image entrypoint is replaced by this script, so the process would
# otherwise stay root and read /root/.config/oxidized (a sample router.db)
# instead of the rendered NetBox config under /home/oxidized.
set -u
if [ "$(id -u)" -eq 0 ]; then
  if [ -x /usr/sbin/update-ca-certificates ] && [ -f /usr/local/share/ca-certificates/insightengine-ca.crt ]; then
    update-ca-certificates >/dev/null 2>&1 || true
  fi
  exec /usr/sbin/runuser -u oxidized -- /bin/sh "$0" "$@"
fi
export HOME=/home/oxidized
# OXIDIZED_HOME is the directory that contains the config file. The image
# also ships a sample at /home/oxidized/config, and a container start command
# that sets OXIDIZED_HOME=/home/oxidized makes Oxidized read that sample and
# crash looking for router.db. Pin the rendered NetBox config instead.
export OXIDIZED_HOME=/home/oxidized/.config/oxidized
cd /home/oxidized || exit 1
pid=""
idle=""
stop() {
  if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  if [ -n "$idle" ]; then kill "$idle" 2>/dev/null || true; fi
  exit 0
}
trap stop TERM INT

port_open() {
  ruby -rsocket -e 'TCPSocket.new("127.0.0.1", 8888).close' >/dev/null 2>&1
}

serve_empty() {
  ruby -rsocket -e '
server = TCPServer.new("127.0.0.1", 8888)
while (sock = server.accept)
  sock.gets
  body = "[]"
  sock.write("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: #{body.bytesize}\r\nConnection: close\r\n\r\n#{body}")
  sock.close
end
' &
  idle=$!
}

while true; do
  oxidized &
  pid=$!
  waited=0
  ready=0
  while [ "$waited" -lt 45 ]; do
    if port_open; then
      ready=1
      break
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 2
    waited=$((waited + 2))
  done
  if [ "$ready" -eq 1 ]; then
    wait "$pid"
    status=$?
    pid=""
    echo "oxidized exited (${status}); retrying" >&2
    sleep 10
    continue
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
  pid=""
  echo "oxidized has no devices yet; serving an empty /nodes and retrying" >&2
  serve_empty
  sleep 30
  if [ -n "$idle" ]; then
    kill "$idle" 2>/dev/null || true
    wait "$idle" 2>/dev/null || true
    idle=""
  fi
done
