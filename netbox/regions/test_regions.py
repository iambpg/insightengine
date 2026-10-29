#!/usr/bin/env python3
"""Catalog checks for netbox/regions/regions.yaml and the idempotent loader."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_regions  # noqa: E402

FILE = Path(__file__).resolve().parent / "regions.yaml"
ISO1 = re.compile(r"^ISO 3166-1 alpha-2: ([A-Z]{2})$")
ISO2 = re.compile(r"^ISO 3166-2: ([A-Z]{2}-[A-Z0-9]+)$")

# Sub-region -> country slug -> number of first-level subdivisions.
TREE = {
    "north-africa": {"eg": 27, "ly": 22, "tn": 24, "dz": 58, "ma": 12, "sd": 18},
    "west-africa": {
        "ng": 0, "gh": 0, "sn": 0, "ci": 0, "ml": 0, "ne": 0, "bf": 0, "gn": 0,
        "bj": 0, "tg": 0, "sl": 0, "lr": 0, "mr": 0, "gm": 0, "cv": 0, "gw": 0,
    },
    "east-africa": {
        "ke": 47, "tz": 31, "ug": 4, "et": 13, "so": 18, "rw": 5, "bi": 18, "ss": 10,
        "dj": 6, "er": 6, "mg": 6, "mu": 12, "sc": 27, "km": 3,
    },
    "central-africa": {"cd": 26, "cg": 12, "cm": 10, "ao": 18, "cf": 17, "ga": 9, "td": 23, "gq": 8, "st": 7},
    "southern-africa": {"za": 9, "zw": 10, "zm": 10, "na": 14, "bw": 16, "mz": 11, "ls": 10, "sz": 4, "mw": 3},
}


def catalog():
    return import_regions.load_regions(FILE)


class RegionDataTest(unittest.TestCase):
    def setUp(self):
        self.regions = catalog()
        self.by_slug = {row["slug"]: row for row in self.regions}

    def test_unique_slugs(self):
        slugs = [row["slug"] for row in self.regions]
        self.assertEqual(len(slugs), len(set(slugs)))
        for slug in slugs:
            self.assertRegex(slug, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            self.assertLessEqual(len(slug), 100)

    def test_parents_exist_and_there_is_no_cycle(self):
        self.assertEqual(import_regions.validate_regions(self.regions), [])
        for row in self.regions:
            parent = row["parent"]
            if parent is not None:
                self.assertIn(parent, self.by_slug)
        self.assertIsNone(self.by_slug["africa"]["parent"])

    def test_hierarchy_and_counts(self):
        children = {}
        for row in self.regions:
            children.setdefault(row["parent"], []).append(row["slug"])
        self.assertEqual(set(children[None]), {"africa"})
        self.assertEqual(set(children["africa"]), set(TREE))
        countries = {}
        for subregion, expected in TREE.items():
            self.assertEqual(self.by_slug[subregion]["parent"], "africa")
            self.assertEqual(self.by_slug[subregion]["description"], "Geographic grouping")
            self.assertEqual(set(children.get(subregion, [])), set(expected))
            countries.update(expected)
        for slug, count in countries.items():
            self.assertEqual(self.by_slug[slug]["parent"] in TREE, True)
            self.assertEqual(len(children.get(slug, [])), count)
            for child in children.get(slug, []):
                self.assertEqual(self.by_slug[child]["parent"], slug)
                self.assertTrue(child.startswith(slug + "-"))
        # Nothing hangs off a subdivision, and no unexpected nodes exist.
        expected_total = 1 + len(TREE) + len(countries) + sum(countries.values())
        self.assertEqual(len(self.regions), expected_total)
        self.assertEqual(expected_total, 644)

    def test_iso_codes_in_descriptions(self):
        seen = set()
        for subregion, countries in TREE.items():
            for slug in countries:
                row = self.by_slug[slug]
                match = ISO1.fullmatch(row["description"])
                self.assertIsNotNone(match, row["description"])
                code = match.group(1)
                self.assertEqual(slug, code.lower())
                self.assertNotIn(code, seen)
                seen.add(code)
                for child_slug, child in self.by_slug.items():
                    if child["parent"] != slug:
                        continue
                    child_match = ISO2.fullmatch(child["description"])
                    self.assertIsNotNone(child_match, child)
                    iso = child_match.group(1)
                    self.assertTrue(iso.startswith(code + "-"))
                    self.assertNotIn(iso, seen)
                    seen.add(iso)

    def test_south_africa_and_documented_choices(self):
        gauteng = self.by_slug["za-gauteng"]
        self.assertEqual(gauteng["name"], "Gauteng")
        self.assertEqual(gauteng["parent"], "za")
        self.assertEqual(gauteng["description"], "ISO 3166-2: ZA-GP")
        self.assertEqual(self.by_slug["za-kwazulu-natal"]["name"], "KwaZulu-Natal")
        self.assertEqual(self.by_slug["za-north-west"]["name"], "North West")
        provinces = {row["slug"] for row in self.regions if row["parent"] == "za"}
        self.assertEqual(provinces, {
            "za-eastern-cape", "za-free-state", "za-gauteng", "za-kwazulu-natal",
            "za-limpopo", "za-mpumalanga", "za-north-west", "za-northern-cape", "za-western-cape",
        })
        uganda = {row["name"] for row in self.regions if row["parent"] == "ug"}
        self.assertEqual(uganda, {"Central", "Eastern", "Northern", "Western"})
        self.assertEqual(len([row for row in self.regions if row["parent"] == "ke"]), 47)
        self.assertEqual(len([row for row in self.regions if row["parent"] == "sc"]), 27)
        self.assertEqual(len([row for row in self.regions if row["parent"] == "mw"]), 3)
        self.assertEqual(self.by_slug["mz-maputo"]["description"], "ISO 3166-2: MZ-L")
        self.assertEqual(self.by_slug["mz-maputo-city"]["description"], "ISO 3166-2: MZ-MPM")
        self.assertEqual(self.by_slug["ci"]["name"], "Côte d'Ivoire")
        self.assertEqual(self.by_slug["cv"]["name"], "Cabo Verde")
        self.assertEqual(self.by_slug["gm"]["name"], "The Gambia")

    def test_rejects_a_duplicate_slug_and_a_missing_parent(self):
        regions = [
            {"slug": "africa", "name": "Africa", "parent": None, "description": "Geographic grouping"},
            {"slug": "africa", "name": "Again", "parent": "missing", "description": ""},
        ]
        errors = import_regions.validate_regions(regions)
        self.assertTrue(any("duplicate slug africa" in item for item in errors))
        self.assertTrue(any("parent missing does not exist" in item for item in errors))


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return json.loads(json.dumps(self._payload))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


class FakeNB:
    def __init__(self, rows=None):
        self.rows = {}
        self.next_id = 1
        self.calls = []
        for row in rows or []:
            self.rows[row["slug"]] = json.loads(json.dumps(row))
            self.next_id = max(self.next_id, row["id"] + 1)

    def list_all(self, path, params=None):
        self.calls.append(("GET", path, params))
        return [json.loads(json.dumps(row)) for row in self.rows.values()]

    def req(self, method, path, body=None, params=None):
        sent = None if body is None else json.loads(json.dumps(body))
        self.calls.append((method, path, sent))
        if method == "POST":
            row = {
                "id": self.next_id,
                "name": body["name"],
                "slug": body["slug"],
                "description": body.get("description") or "",
                "parent": {"id": body["parent"]} if body.get("parent") else None,
                "comments": "",
            }
            self.next_id += 1
            self.rows[row["slug"]] = row
            return FakeResponse(201, row)
        if method == "PATCH":
            pk = int(path.rstrip("/").rsplit("/", 1)[-1])
            row = next(item for item in self.rows.values() if item["id"] == pk)
            for key, value in body.items():
                if key == "parent":
                    row["parent"] = {"id": value} if value else None
                else:
                    row[key] = value
            return FakeResponse(200, row)
        if method == "DELETE":
            return FakeResponse(204, {})
        raise AssertionError(method)


class SyncTest(unittest.TestCase):
    def test_second_run_creates_nothing_and_preserves_other_fields(self):
        regions = catalog()
        client = FakeNB()
        first = import_regions.sync_regions(client, regions)
        self.assertEqual(first["regions_created"], len(regions))
        self.assertEqual(first["failures"], [])
        created = client.rows["za-gauteng"]
        self.assertEqual(created["description"], "ISO 3166-2: ZA-GP")
        client.calls.clear()
        second = import_regions.sync_regions(client, regions)
        self.assertEqual(second["regions_created"], 0)
        self.assertEqual(second["regions_updated"], 0)
        self.assertEqual(second["regions_unchanged"], len(regions))
        self.assertEqual([call[0] for call in client.calls], ["GET"])

        client.calls.clear()
        client.rows["za-gauteng"]["name"] = "Not Gauteng"
        client.rows["za-gauteng"]["description"] = "operator note"
        client.rows["za-gauteng"]["comments"] = "keep me"
        client.rows["za-gauteng"]["parent"] = None
        client.rows["zz-custom"] = {
            "id": 9000, "name": "Custom", "slug": "zz-custom", "description": "leave me",
            "parent": None, "comments": "",
        }
        third = import_regions.sync_regions(client, regions)
        self.assertEqual(third["regions_created"], 0)
        self.assertEqual(third["regions_updated"], 1)
        self.assertFalse(any(call[0] == "DELETE" for call in client.calls))
        patches = [call for call in client.calls if call[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(set(patches[0][2]), {"name", "parent"})
        restored = client.rows["za-gauteng"]
        self.assertEqual(restored["name"], "Gauteng")
        self.assertEqual(restored["description"], "operator note")
        self.assertEqual(restored["comments"], "keep me")
        self.assertEqual(restored["parent"]["id"], client.rows["za"]["id"])
        self.assertIn("zz-custom", client.rows)


if __name__ == "__main__":
    unittest.main()
