#!/usr/bin/env python3
"""The component backfill creates only what a device is missing, matched by name."""
import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill_components as backfill  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "backfill_components.py"


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return json.loads(json.dumps(self._payload))


class FakeNB:
    def __init__(self):
        self.devices = []
        self.templates = {}
        self.components = {}
        self.calls = []
        self.next_id = 1000
        self.fail_devices = set()

    def list_all(self, path, params=None):
        query = dict(params or {})
        self.calls.append(("GET", path, query))
        if path == "/api/dcim/devices/":
            return json.loads(json.dumps(self.devices))
        if "device_type_id" in query:
            rows = self.templates.get((path, query["device_type_id"]), [])
            return json.loads(json.dumps(rows))
        if "device_id" in query:
            if query["device_id"] in self.fail_devices:
                raise RuntimeError("boom")
            rows = self.components.get((path, query["device_id"]), [])
            return json.loads(json.dumps(rows))
        raise AssertionError(path)

    def req(self, method, path, body=None, params=None):
        sent = None if body is None else json.loads(json.dumps(body))
        self.calls.append((method, path, sent))
        if method != "POST":
            return FakeResponse(405, {"detail": method})
        rows = sent if isinstance(sent, list) else [sent]
        if isinstance(sent, list) and any(row.get("name") == "explode" for row in rows):
            return FakeResponse(400, {"detail": "bulk refused"})
        made = []
        for row in rows:
            if row.get("name") == "explode":
                return FakeResponse(400, {"name": ["bad"]})
            item = dict(row)
            item["id"] = self.next_id
            self.next_id += 1
            self.components.setdefault((path, row["device"]), []).append(item)
            made.append(item)
        payload = made if isinstance(sent, list) else made[0]
        return FakeResponse(201, payload)


def _device(ident, name, dtype):
    return {"id": ident, "name": name, "device_type": {"id": dtype, "model": "m"}}


def _template(path, dtype, row):
    return (path, dtype, row)


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeNB()
        self.client.devices = [
            _device(1, "sw1", 10),
            _device(2, "stub", 11),
        ]
        iface = backfill.TEMPLATE_PATH["interfaces"]
        console = backfill.TEMPLATE_PATH["console-ports"]
        module = backfill.TEMPLATE_PATH["module-bays"]
        power_port = backfill.TEMPLATE_PATH["power-ports"]
        power_outlet = backfill.TEMPLATE_PATH["power-outlets"]
        rear = backfill.TEMPLATE_PATH["rear-ports"]
        front = backfill.TEMPLATE_PATH["front-ports"]
        self.client.templates[(iface, 10)] = [
            {"id": 1, "name": "GigabitEthernet1/0/1", "type": "1000base-t", "poe_mode": "pse",
             "poe_type": "type2-ieee802.3at", "device_type": {"id": 10}},
            {"id": 2, "name": "GigabitEthernet1/0/2", "type": "1000base-t", "enabled": True,
             "device_type": {"id": 10}, "bridge": {"id": 1, "name": "GigabitEthernet1/0/1"}},
            {"id": 3, "name": "GigabitEthernet0/0", "type": "1000base-t", "mgmt_only": True,
             "device_type": {"id": 10}},
        ]
        self.client.templates[(console, 10)] = [
            {"id": 4, "name": "con 0", "type": "rj-45", "device_type": {"id": 10}},
            {"id": 5, "name": "usb", "type": {"value": "usb-mini-b", "label": "USB Mini-B"},
             "label": "USB", "device_type": {"id": 10}},
        ]
        self.client.templates[(module, 10)] = [
            {"id": 6, "name": "FAN 3", "position": "3", "device_type": {"id": 10}},
        ]
        self.client.templates[(power_port, 10)] = [
            {"id": 8, "name": "PSU1", "type": "iec-60320-c14", "device_type": {"id": 10}},
        ]
        self.client.templates[(power_outlet, 10)] = [
            {"id": 9, "name": "Outlet1", "type": "iec-60320-c13",
             "power_port": {"id": 8, "name": "PSU1"}, "device_type": {"id": 10}},
        ]
        self.client.templates[(rear, 10)] = [
            {"id": 7, "name": "Rear A", "type": "8p8c", "positions": 1, "device_type": {"id": 10}},
        ]
        self.client.templates[(front, 10)] = [
            {"id": 12, "name": "Front A", "type": "8p8c", "positions": 1, "device_type": {"id": 10},
             "rear_ports": [{"position": 1, "rear_port": 7, "rear_port_position": 2}]},
            {"id": 13, "name": "Front B", "type": "8p8c", "device_type": {"id": 10},
             "rear_port": "Rear A", "rear_port_position": 1},
        ]
        # Existing components: Gi1/0/1 was deleted. Gi0/0 stays, plus a custom name.
        # usb and FAN 3 and Front A and the power outlet are missing.
        # Rear A exists so Front A must map to it by name.
        iface_path = backfill.COMPONENT_PATH["interfaces"]
        self.client.components[(iface_path, 1)] = [
            {"id": 50, "name": "GigabitEthernet0/0", "type": "1000base-t", "description": "keep me", "device": 1},
            {"id": 51, "name": "CustomUplink", "type": "10gbase-x-sfpp", "description": "operator", "device": 1},
        ]
        self.client.components[(backfill.COMPONENT_PATH["console-ports"], 1)] = [
            {"id": 60, "name": "con 0", "type": "rj-45", "device": 1},
        ]
        self.client.components[(backfill.COMPONENT_PATH["rear-ports"], 1)] = [
            {"id": 99, "name": "Rear A", "type": "8p8c", "device": 1},
        ]
        self.kept = copy.deepcopy(self.client.components)

    def test_creates_only_missing_and_leaves_custom_components(self):
        stats = backfill.backfill(self.client)
        self.assertEqual(stats["failures"], [])
        self.assertEqual(stats["devices_scanned"], 2)
        self.assertEqual(stats["devices_skipped"], 1)
        self.assertEqual(stats["devices_changed"], 1)
        self.assertEqual(stats["created"]["interfaces"], 2)
        self.assertEqual(stats["created"]["console-ports"], 1)
        self.assertEqual(stats["created"]["module-bays"], 1)
        self.assertEqual(stats["created"]["power-ports"], 1)
        self.assertEqual(stats["created"]["power-outlets"], 1)
        self.assertEqual(stats["created"]["rear-ports"], 0)
        self.assertEqual(stats["created"]["front-ports"], 2)
        self.assertEqual(stats["created"]["device-bays"], 0)
        self.assertFalse(any(call[0] in {"PATCH", "PUT", "DELETE"} for call in self.client.calls))

        interfaces = self.client.components[(backfill.COMPONENT_PATH["interfaces"], 1)]
        by_name = {row["name"]: row for row in interfaces}
        self.assertEqual(by_name["GigabitEthernet0/0"]["id"], 50)
        self.assertEqual(by_name["GigabitEthernet0/0"]["description"], "keep me")
        self.assertEqual(by_name["CustomUplink"]["id"], 51)
        self.assertEqual(by_name["CustomUplink"]["type"], "10gbase-x-sfpp")
        self.assertEqual(by_name["GigabitEthernet1/0/1"]["type"], "1000base-t")
        self.assertEqual(by_name["GigabitEthernet1/0/1"]["poe_mode"], "pse")
        self.assertNotIn("bridge", by_name["GigabitEthernet1/0/1"])
        # Gi1/0/2 bridges the device interface named GigabitEthernet1/0/1, not template id 1.
        self.assertEqual(by_name["GigabitEthernet1/0/2"]["bridge"], by_name["GigabitEthernet1/0/1"]["id"])
        self.assertNotEqual(by_name["GigabitEthernet1/0/2"]["bridge"], 1)

        outlets = self.client.components[(backfill.COMPONENT_PATH["power-outlets"], 1)]
        ports = self.client.components[(backfill.COMPONENT_PATH["power-ports"], 1)]
        self.assertEqual(outlets[0]["power_port"], ports[0]["id"])
        self.assertNotEqual(outlets[0]["power_port"], 8)

        fronts = {row["name"]: row for row in self.client.components[(backfill.COMPONENT_PATH["front-ports"], 1)]}
        self.assertEqual(fronts["Front A"]["rear_ports"], [
            {"position": 1, "rear_port": 99, "rear_port_position": 2},
        ])
        self.assertEqual(fronts["Front B"]["rear_ports"][0]["rear_port"], 99)
        self.assertNotEqual(fronts["Front A"]["rear_ports"][0]["rear_port"], 7)

        posts = [call for call in self.client.calls if call[0] == "POST"]
        posted_names = []
        for call in posts:
            body = call[2]
            rows = body if isinstance(body, list) else [body]
            posted_names.extend(row["name"] for row in rows)
        self.assertNotIn("CustomUplink", posted_names)
        self.assertNotIn("GigabitEthernet0/0", posted_names)
        self.assertNotIn("con 0", posted_names)
        self.assertNotIn("Rear A", posted_names)
        usb_body = None
        for call in posts:
            body = call[2]
            rows = body if isinstance(body, list) else [body]
            for row in rows:
                if row["name"] == "usb":
                    usb_body = row
        self.assertEqual(usb_body["type"], "usb-mini-b")

    def test_second_run_and_dry_run_create_nothing(self):
        first = backfill.backfill(self.client)
        self.assertEqual(first["devices_changed"], 1)
        self.client.calls.clear()
        second = backfill.backfill(self.client)
        self.assertEqual(second["created"], {kind: 0 for kind in backfill.KINDS})
        self.assertEqual(second["devices_changed"], 0)
        self.assertEqual(second["failures"], [])
        self.assertEqual([call[0] for call in self.client.calls], ["GET"] * len(self.client.calls))

        fresh = FakeNB()
        fresh.devices = copy.deepcopy(self.client.devices)
        fresh.templates = copy.deepcopy(self.client.templates)
        fresh.components = copy.deepcopy(self.kept)
        before = copy.deepcopy(fresh.components)
        dry = backfill.backfill(fresh, dry_run=True)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["created"]["interfaces"], 2)
        self.assertEqual(dry["created"]["front-ports"], 2)
        self.assertEqual(dry["devices_changed"], 1)
        self.assertEqual(dry["failures"], [])
        self.assertFalse(any(call[0] == "POST" for call in fresh.calls))
        self.assertEqual(fresh.components, before)

    def test_recreates_a_missing_rear_port_then_maps_the_front_port_to_it(self):
        self.client.components[(backfill.COMPONENT_PATH["rear-ports"], 1)] = []
        stats = backfill.backfill(self.client)
        self.assertEqual(stats["failures"], [])
        self.assertEqual(stats["created"]["rear-ports"], 1)
        rear = self.client.components[(backfill.COMPONENT_PATH["rear-ports"], 1)][0]
        front = {row["name"]: row for row in self.client.components[(backfill.COMPONENT_PATH["front-ports"], 1)]}
        self.assertEqual(front["Front A"]["rear_ports"][0]["rear_port"], rear["id"])
        self.assertNotEqual(rear["id"], 7)

    def test_one_bad_device_does_not_stop_the_walk(self):
        self.client.devices.append(_device(3, "bad", 10))
        self.client.fail_devices.add(3)
        stats = backfill.backfill(self.client)
        self.assertEqual(stats["devices_scanned"], 3)
        self.assertEqual(stats["devices_changed"], 1)
        self.assertEqual(len(stats["failures"]), 1)
        self.assertEqual(stats["failures"][0]["device"], "bad")
        self.assertIn("GigabitEthernet1/0/1", {
            row["name"] for row in self.client.components[(backfill.COMPONENT_PATH["interfaces"], 1)]
        })
        self.assertNotIn((backfill.COMPONENT_PATH["interfaces"], 3), self.client.components)

    def test_a_bad_component_does_not_drop_the_rest_of_the_chunk(self):
        self.client.templates[(backfill.TEMPLATE_PATH["console-ports"], 10)].append(
            {"id": 40, "name": "explode", "type": "rj-45", "device_type": {"id": 10}},
        )
        stats = backfill.backfill(self.client)
        names = {row["name"] for row in self.client.components[(backfill.COMPONENT_PATH["console-ports"], 1)]}
        self.assertIn("usb", names)
        self.assertNotIn("explode", names)
        self.assertTrue(any(item["kind"] == "console-ports" and "explode" in item["error"] for item in stats["failures"]))
        self.assertGreater(stats["created"]["interfaces"], 0)

    def test_disabled_flag_reports_and_does_not_connect(self):
        self.assertTrue(backfill.backfill_enabled("true"))
        self.assertTrue(backfill.backfill_enabled(""))
        self.assertTrue(backfill.backfill_enabled("yes"))
        for value in ("false", "0", "no", "off", "FALSE"):
            self.assertFalse(backfill.backfill_enabled(value))
        env = os.environ.copy()
        env["NETBOX_BACKFILL_COMPONENTS"] = "false"
        env.pop("NETBOX_TOKEN", None)
        env.pop("NETBOX_TOKEN_FILE", None)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--dry-run", "--report", "/tmp/component-backfill-disabled.json"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        line = completed.stdout.strip().splitlines()[-1]
        payload = json.loads(line)
        self.assertEqual(payload["devices_scanned"], 0)
        self.assertEqual(payload["devices_changed"], 0)
        self.assertEqual(payload["failures"], 0)
        self.assertTrue(payload["disabled"])
        self.assertTrue(payload["dry_run"])
        self.assertNotIn("nbt_", completed.stdout)


if __name__ == "__main__":
    unittest.main()
