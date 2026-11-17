"""Forward syslog to Telegraf with the sender address on the front.

Cisco often sends a timestamp and a timezone, and no hostname. The address
the packet came from is what ties the line to a device. Telegraf then stores
that address as the sender label.
"""

from __future__ import annotations

import os
import socket
import threading

DEST = os.environ.get("TELEGRAF_ADDR", "telegraf-syslog:6514")
LISTEN = int(os.environ.get("LISTEN_PORT", "6514"))


def _target() -> tuple[str, int]:
    host, _, port = DEST.rpartition(":")
    return host, int(port or "6514")


def _prefix(data: bytes, ip: str) -> bytes:
    if data.startswith(b"@"):
        return data
    return b"@" + ip.encode("ascii", "ignore") + b" " + data


def _udp() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", LISTEN))
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = _target()
    while True:
        data, addr = sock.recvfrom(65535)
        if data:
            out.sendto(_prefix(data, addr[0]), target)


def _handle(conn: socket.socket, ip: str) -> None:
    out = socket.create_connection(_target(), timeout=10)
    try:
        buf = b""
        while True:
            chunk = conn.recv(65535)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line:
                    out.sendall(_prefix(line, ip) + b"\n")
        if buf:
            out.sendall(_prefix(buf, ip))
    finally:
        conn.close()
        out.close()


def _tcp() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", LISTEN))
    server.listen(128)
    while True:
        conn, addr = server.accept()
        threading.Thread(target=_handle, args=(conn, addr[0]), daemon=True).start()


if __name__ == "__main__":
    threading.Thread(target=_tcp, daemon=True).start()
    _udp()
