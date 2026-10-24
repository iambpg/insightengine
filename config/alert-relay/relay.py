#!/usr/bin/env python3
"""Internal alert relay (placeholder). Alertmanager -> POST /alert -> every
enabled destination in destinations.json. Destination URLs are never logged."""
import json
import logging
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLIENT_SLUG = os.environ.get("CLIENT_SLUG", "")
CLIENT_NAME = os.environ.get("CLIENT_NAME", "")
DEST_FILE = os.environ.get("DESTINATIONS_FILE", "/etc/alert-relay/destinations.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alert-relay")


def load_destinations():
    try:
        with open(DEST_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log.error("cannot read destinations: %s", type(exc).__name__)
        return []
    return [d for d in data.get("destinations", []) if d.get("enabled") and str(d.get("url", "")).startswith(("http://", "https://"))]


def make_title(payload):
    labels = payload.get("commonLabels", {})
    status = payload.get("status", "firing").upper()
    return "[%s] %s - %s" % (status, CLIENT_NAME or CLIENT_SLUG, labels.get("alertname", "alert"))


def forward(dest, body):
    req = urllib.request.Request(dest["url"], data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - URL comes from admin-managed file
        return resp.status


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, text=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(text)))
        self.end_headers()
        self.wfile.write(text)

    def do_GET(self):  # noqa: N802
        self._reply(200 if self.path == "/healthz" else 404, b"ok" if self.path == "/healthz" else b"")

    def do_POST(self):  # noqa: N802
        if self.path != "/alert":
            return self._reply(404)
        length = int(self.headers.get("Content-Length", "0"))
        if length > 5_000_000:
            return self._reply(413)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._reply(400)
        payload.update({"client": CLIENT_SLUG, "client_name": CLIENT_NAME, "title": make_title(payload)})
        body = json.dumps(payload).encode()
        dests = load_destinations()
        failed = 0
        for dest in dests:
            try:
                forward(dest, body)
                log.info("forwarded to %s", dest.get("name", "?"))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.error("destination %s failed: %s", dest.get("name", "?"), type(exc).__name__)
        # 502 makes Alertmanager retry when every destination failed
        return self._reply(502 if dests and failed == len(dests) else 200)

    def log_message(self, *args):  # silence default access log
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
