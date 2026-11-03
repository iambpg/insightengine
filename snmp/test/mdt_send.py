#!/usr/bin/env python3
"""Push a few GPB-KV dial-out messages at the local Telegraf MDT listener."""

from __future__ import annotations

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
    client = "Cisco-IOS-XE-wireless-client-oper:client-oper-data"
    rows = [
        message(tele, "wlc-9800", client + "/common-oper-data", "61000", [
            field(tele, "client-mac", string_value="aa:bb:cc:dd:ee:01"),
        ], [
            field(tele, "ap-name", string_value="AP-1"),
            field(tele, "ms-ap-slot-id", uint32_value=1),
        ], when),
        message(tele, "wlc-9800", client + "/traffic-stats", "61001", [
            field(tele, "ms-mac-address", string_value="aa:bb:cc:dd:ee:01"),
        ], [
            field(tele, "most-recent-rssi", sint32_value=-60),
            field(tele, "most-recent-snr", uint32_value=25),
        ], when),
        message(tele, "wlc-9800", client + "/traffic-stats", "61001", [
            field(tele, "ms-mac-address", string_value="aa:bb:cc:dd:ee:02"),
            field(tele, "ap-name", string_value="AP-1"),
            field(tele, "ms-ap-slot-id", uint32_value=1),
        ], [
            field(tele, "most-recent-rssi", sint32_value=-80),
            field(tele, "most-recent-snr", uint32_value=15),
        ], when),
        message(tele, "wlc-9800", "Cisco-IOS-XE-wireless-rrm-oper:rrm-oper-data/rrm-measurement", "61002", [
            field(tele, "wtp-mac", string_value="00:11:22:33:44:55"),
            field(tele, "radio-slot-id", uint32_value=1),
        ], [
            field(tele, "cca-util-percentage", uint32_value=55),
            field(tele, "rx-noise-channel-utilization", uint32_value=12),
        ], when),
        message(tele, "wlc-9800", "Cisco-IOS-XE-wireless-access-point-oper:access-point-oper-data/capwap-data", "61003", [
            field(tele, "name", string_value="AP-1"),
        ], [
            field(tele, "ap-operation-state", string_value="registered"),
            field(tele, "reboot-reason", string_value="none"),
        ], when),
        message(tele, "edge-1", "Cisco-IOS-XE-sdwan-oper:sdwan-oper-data/app-route/statistics", "62000", [
            field(tele, "local-color", string_value="biz-internet"),
            field(tele, "remote-color", string_value="mpls"),
            field(tele, "dst-ip", string_value="10.9.0.2"),
        ], [
            field(tele, "mean-loss", uint32_value=4),
            field(tele, "mean-latency", uint32_value=22),
            field(tele, "mean-jitter", uint32_value=3),
            field(tele, "state", string_value="up"),
        ], when),
    ]

    def generate():
        for index, row in enumerate(rows, 1):
            yield mdt_dialout_pb2.MdtDialoutArgs(ReqId=index, data=row.SerializeToString())

    channel = grpc.insecure_channel("127.0.0.1:57000")
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
