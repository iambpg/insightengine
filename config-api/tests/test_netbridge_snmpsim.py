"""Walk a real snmpsim agent. Docker is not required; the same responder image is snmpsim 1.1.7.

The 5000-row case is test_walk_handles_five_thousand_rows. This file checks the
walker against snmpsim's UDP agent, including GetBulk across more than one packet.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from ie_config.netbridge.snmp import AIRE_IP, AIRE_MODEL, AIRE_NAME, AIRE_SERIAL, CDP_AP, CDP_NEIGH, CDP_PORT, XE_NAME, scan_wlc

SIM = shutil.which("snmpsim-command-responder") or os.path.expanduser("~/.local/bin/snmpsim-command-responder")
AP_COUNT = 80


pytestmark = pytest.mark.skipif(not os.path.isfile(SIM), reason="snmpsim-command-responder is not installed")


def _line(oid: str, kind: str, value: str) -> str:
    return "%s|%s|%s\n" % (oid, kind, value)


def _write(path: Path) -> None:
    rows = []
    for number in range(1, AP_COUNT + 1):
        rows.append(_line("%s.%d" % (AIRE_NAME, number), "4", "ap-%04d" % number))
        rows.append(_line("%s.%d" % (AIRE_MODEL, number), "4", "CW9164" if number % 2 == 0 else "C9120AXI"))
        rows.append(_line("%s.%d" % (AIRE_SERIAL, number), "4", "FGL%05d" % number))
        rows.append(_line("%s.%d" % (AIRE_IP, number), "4", "10.8.%d.%d" % (number // 250, number % 250)))
        rows.append(_line("%s.%d" % (CDP_AP, number), "4", "ap-%04d" % number))
        rows.append(_line("%s.%d" % (CDP_NEIGH, number), "4", "sw-edge.pnp.co.za"))
        rows.append(_line("%s.%d" % (CDP_PORT, number), "4", "Gi1/0/%d" % ((number % 48) + 1)))
    # One Catalyst 9800 name that is not in the AireOS table.
    rows.append(_line(XE_NAME + ".9.9.9.9.9.9", "4", "ap-xe-only"))
    rows.sort(key=lambda row: tuple(int(part) for part in row.split("|", 1)[0].split(".") if part))
    path.write_text("".join(rows), encoding="utf-8")


def _port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_snmpsim_wlc_tables(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write(data / "public.snmprec")
    port = _port()
    proc = subprocess.Popen(
        [SIM, "--data-dir=%s" % data, "--agent-udpv4-endpoint=127.0.0.1:%s" % port, "--logging-method=null"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 15
        result = {"ok": False, "aps": []}
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail("snmpsim exited %s" % proc.returncode)
            result = scan_wlc("127.0.0.1", port, "public", timeout=1.0)
            if result.get("ok") and len(result.get("aps") or []) >= AP_COUNT:
                break
            time.sleep(0.3)
        aps = result.get("aps") or []
        assert result.get("ok") is True
        assert len(aps) == AP_COUNT + 1
        by_name = {ap["name"]: ap for ap in aps}
        assert by_name["ap-0002"]["model"] == "CW9164"
        assert by_name["ap-0002"]["serial"] == "FGL00002"
        assert by_name["ap-0002"]["neighbor"] == "sw-edge.pnp.co.za"
        assert by_name["ap-0002"]["neighbor_port"].startswith("Gi1/0/")
        assert by_name["ap-xe-only"]["platform"] == "ios-xe"
        models = {ap["model"] for ap in aps if ap["model"]}
        assert "C9120AXI" in models and "CW9164" in models
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
