#!/usr/bin/env python3
"""Push a few GPB-KV dial-out messages at the local Telegraf MDT listener."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GEN = Path("/tmp/ie-experience/mdt-py")


def compile_stubs() -> None:
    GEN.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([
        sys.executable, "-m", "grpc_tools.protoc",
        "-I", str(ROOT / "mdt"),
        "--python_out", str(GEN),
        "--grpc_python_out", str(GEN),
        str(ROOT / "mdt" / "telemetry_bis.proto"),
        str(ROOT / "mdt" / "mdt_dialout.proto"),
    ])


def field(mod, name, **kind):
    return mod.TelemetryField(name=name, **kind)


def _typed(mod, name, value):
    text = str(value)
    if text.startswith("-") and text[1:].isdigit():
        return field(mod, name, sint32_value=int(text))
    if text.isdigit():
        number = int(text)
        if number > 4294967295:
            return field(mod, name, uint64_value=number)
        return field(mod, name, uint32_value=number)
    return field(mod, name, string_value=text)


def row(mod, keys, content):
    # IOS-XE GPB-KV is one TelemetryField whose children are "keys" and "content".
    return mod.TelemetryField(fields=[
        mod.TelemetryField(name="keys", fields=keys),
        mod.TelemetryField(name="content", fields=content),
    ])


def message(mod, node, path, subscription, keys, content, when):
    return mod.Telemetry(
        node_id_str=node,
        subscription_id_str=subscription,
        encoding_path=path,
        collection_id=1,
        msg_timestamp=when,
        data_gpbkv=[row(mod, keys, content)],
    )


def main() -> int:
    try:
        import grpc  # noqa: F401
        from grpc_tools import protoc  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "grpcio==1.67.1", "grpcio-tools==1.67.1"])
    compile_stubs()
    sys.path.insert(0, str(GEN))
    import grpc
    import mdt_dialout_pb2
    import mdt_dialout_pb2_grpc
    import telemetry_bis_pb2 as tele

    when = int(time.time() * 1000)
    sys.path.insert(0, str(ROOT.parents[1].parent / "config" / "telegraf" / "wlc"))
    import catalog
    rows = []
    for index, sample in enumerate(catalog.sample_kvgpb()):
        node = "edge-1" if "sdwan" in sample["path"] else "wlc-9800"
        rows.append(message(
            tele, node, sample["path"], str(61000 + index),
            [_typed(tele, name, value) for name, value in sample["keys"]],
            [_typed(tele, name, value) for name, value in sample["content"]],
            when,
        ))
    # Second client so the per-radio rollup is an average, still dropped when store_clients=0.
    rows.append(message(tele, "wlc-9800", "Cisco-IOS-XE-wireless-client-oper:client-oper-data/traffic-stats", "61001", [
        field(tele, "ms-mac-address", string_value="aa:bb:cc:dd:ee:02"),
        field(tele, "ap-name", string_value="AP-1"),
        field(tele, "ms-ap-slot-id", uint32_value=1),
    ], [
        field(tele, "most-recent-rssi", sint32_value=-80),
        field(tele, "most-recent-snr", uint32_value=15),
    ], when))
    rows.append(message(tele, "edge-1", "Cisco-IOS-XE-sdwan-oper:sdwan-oper-data/app-route/statistics", "62000", [
        field(tele, "local-color", string_value="biz-internet"),
        field(tele, "remote-color", string_value="mpls"),
        field(tele, "dst-ip", string_value="10.9.0.2"),
    ], [
        field(tele, "mean-loss", uint32_value=4),
        field(tele, "mean-latency", uint32_value=22),
        field(tele, "mean-jitter", uint32_value=3),
        field(tele, "state", string_value="up"),
    ], when))

    def generate():
        for index, row in enumerate(rows, 1):
            yield mdt_dialout_pb2.MdtDialoutArgs(ReqId=index, data=row.SerializeToString())

    port = os.environ.get("IE_MDT_PORT") or "57500"
    channel = grpc.insecure_channel("127.0.0.1:%s" % port)
    grpc.channel_ready_future(channel).result(timeout=20)
    stub = mdt_dialout_pb2_grpc.gRPCMdtDialoutStub(channel)
    call = stub.MdtDialout(generate(), timeout=20)
    try:
        next(call)
    except StopIteration:
        pass
    except Exception as exc:
        # Telegraf often half-closes without a reply. The samples are already sent.
        print("dialout finished: %s" % exc.__class__.__name__)
    print("sent %d telemetry messages" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
