#!/usr/bin/env python3
"""Telegraf 1.38.3 must accept normalize.star, and the image must ship catalog.py.

go.starlark.net in Telegraf 1.38.3 enables recursion, sets, and global
reassignment. It does not enable while loops or top-level control flow.
A while loop aborts agent startup, so the collector never binds the dial-out
port. This test loads the real script with the 1.38.3 binary and rejects a
while loop, so a looser interpreter cannot hide a regression.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WLC = Path(__file__).resolve().parent
TELEGRAF_VERSION = "1.38.3"
TARBALL_SHA256 = {
    "amd64": "3d0f74bff0577ce1eda7423a6d4cbe6a4ac9fae5ee1bb2f2b5550d2435c69e96",
}
DIALECT_MARKERS = (
    "does not support",
    "could not initialize processor",
    "error parsing",
    "invalid configuration",
    "Error running agent",
)


def _arch() -> str:
    machine = os.uname().machine
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


def _telegraf_bin() -> Path:
    override = os.environ.get("TELEGRAF_BIN")
    if override:
        binary = Path(override)
        if not binary.is_file():
            raise unittest.SkipTest("TELEGRAF_BIN is not a file: %s" % binary)
        return binary
    arch = _arch()
    digest = TARBALL_SHA256.get(arch)
    if not digest:
        raise unittest.SkipTest("no pinned Telegraf %s tarball for %s" % (TELEGRAF_VERSION, arch))
    cache = Path.home() / ".cache" / "insightengine" / ("telegraf-" + TELEGRAF_VERSION) / "telegraf"
    if cache.is_file():
        return cache
    url = "https://dl.influxdata.com/telegraf/releases/telegraf-%s_linux_%s.tar.gz" % (TELEGRAF_VERSION, arch)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        blob = Path(tmp) / "telegraf.tar.gz"
        request = urllib.request.Request(url, headers={"User-Agent": "insightengine-telegraf-test/1.0"})
        hasher = hashlib.sha256()
        with urllib.request.urlopen(request, timeout=180) as response, blob.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                hasher.update(chunk)
        got = hasher.hexdigest()
        if got != digest:
            raise AssertionError("telegraf tarball sha256 %s != %s" % (got, digest))
        with tarfile.open(blob, "r:gz") as archive:
            archive.extractall(tmp, filter="data")
        found = next(Path(tmp).rglob("usr/bin/telegraf"))
        shutil.copy2(found, cache)
        cache.chmod(cache.stat().st_mode | stat.S_IEXEC)
    return cache


def _run_telegraf(binary: Path, config: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CLIENT_SLUG"] = "ci"
    return subprocess.run(
        [str(binary), "--config", str(config), "--test", "--non-strict-env-handling"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _code_text(path: Path) -> str:
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        kept.append(line)
    return "\n".join(kept)


def _service_block(name: str, follower: str) -> str:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    section = text.split("\n  %s:\n" % name, 1)[1]
    return section.split("\n  %s:\n" % follower, 1)[0]


class CatalogPackagingTests(unittest.TestCase):
    def test_dockerfile_copies_catalog_beside_the_renderer(self) -> None:
        text = (WLC / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY catalog.py /usr/local/bin/catalog.py", text)
        self.assertIn("COPY render_wlc.py /usr/local/bin/render_wlc.py", text)
        self.assertIn("ENV PYTHONPATH=/usr/local/bin:/etc/telegraf", text)

    def test_compose_mounts_catalog_and_sets_pythonpath(self) -> None:
        block = _service_block("telegraf-wlc", "telegraf-host")
        self.assertIn("PYTHONPATH: /usr/local/bin:/etc/telegraf", block)
        self.assertIn("./config/telegraf/wlc:/etc/telegraf:ro", block)
        self.assertIn("./config/telegraf/wlc/catalog.py:/usr/local/bin/catalog.py:ro", block)

    def test_entrypoint_puts_both_directories_on_pythonpath(self) -> None:
        text = (WLC / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="/usr/local/bin:/etc/telegraf', text)

    def test_render_imports_catalog_from_the_script_dir_or_an_extra_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script_only = root / "script-only"
            beside = root / "beside"
            extra = root / "extra"
            both_script = root / "both-script"
            both_extra = root / "both-extra"
            for path in (script_only, beside, extra, both_script, both_extra):
                path.mkdir()
            shutil.copy(WLC / "render_wlc.py", script_only / "render_wlc.py")
            shutil.copy(WLC / "render_wlc.py", beside / "render_wlc.py")
            shutil.copy(WLC / "catalog.py", beside / "catalog.py")
            shutil.copy(WLC / "render_wlc.py", both_script / "render_wlc.py")
            shutil.copy(WLC / "catalog.py", both_script / "catalog.py")
            (both_extra / "catalog.py").write_text('MDT_SUBS = "extra"\nAIREOS_TABLES = {}\n', encoding="utf-8")
            (extra / "catalog.py").write_text("MDT_SUBS = []\nAIREOS_TABLES = {}\n", encoding="utf-8")
            shutil.copy(WLC / "render_wlc.py", extra / "render_wlc.py")

            missing = self._render(script_only, None)
            self.assertNotEqual(missing.returncode, 0, missing.stderr)
            self.assertIn("ModuleNotFoundError", missing.stderr)

            found = self._render(beside, None)
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertIn("Generated from NetBox", (beside / "out.conf").read_text(encoding="utf-8"))

            mounted = self._render(extra, extra)
            self.assertEqual(mounted.returncode, 0, mounted.stderr)

            winner = self._which_catalog(both_script, both_extra)
            self.assertTrue(winner.endswith("/both-script/catalog.py"), winner)

    def _render(self, script_dir: Path, catalog_dir: Path | None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["IE_NETBOX_SD_URL"] = ""
        env["IE_NETBOX_TOKEN_FILE"] = str(script_dir / "no-token")
        if catalog_dir is None:
            env["IE_WLC_CATALOG_DIR"] = str(script_dir / "missing-catalog-dir")
        else:
            env["IE_WLC_CATALOG_DIR"] = str(catalog_dir)
        return subprocess.run(
            [sys.executable, str(script_dir / "render_wlc.py"), "-o", str(script_dir / "out.conf")],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def _which_catalog(self, script_dir: Path, catalog_dir: Path) -> str:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["IE_WLC_CATALOG_DIR"] = str(catalog_dir)
        code = (
            "import importlib.util\n"
            "from pathlib import Path\n"
            "path = Path(%r) / 'render_wlc.py'\n"
            "spec = importlib.util.spec_from_file_location('render_wlc_under_test', path)\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "import catalog\n"
            "print(catalog.__file__)\n"
        ) % str(script_dir)
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()


class StarlarkDialectTests(unittest.TestCase):
    binary: Path

    @classmethod
    def setUpClass(cls) -> None:
        binary = _telegraf_bin()
        version = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if TELEGRAF_VERSION not in (version.stdout + version.stderr):
            raise AssertionError("need Telegraf %s, got %s" % (TELEGRAF_VERSION, version.stdout.strip()))
        cls.binary = binary

    def test_star_files_have_no_while_loops(self) -> None:
        stars = sorted((ROOT / "config" / "telegraf").rglob("*.star"))
        self.assertTrue(stars)
        for path in stars:
            code = _code_text(path)
            self.assertNotRegex(code, r"\bwhile\b", "%s uses while" % path)

    def test_host_api_and_syslog_have_no_starlark_scripts(self) -> None:
        for name in ("host", "api", "syslog"):
            base = ROOT / "config" / "telegraf" / name
            self.assertFalse(list(base.rglob("*.star")), name)
            for conf in base.rglob("*.conf"):
                self.assertNotIn("processors.starlark", conf.read_text(encoding="utf-8"), str(conf))

    def test_dialect_rejects_while_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "while.star"
            script.write_text(
                "def apply(metric):\n    i = 0\n    while i < 1:\n        i = i + 1\n    return metric\n",
                encoding="utf-8",
            )
            config = root / "telegraf.conf"
            config.write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "10s"',
                    "  omit_hostname = true",
                    "[[inputs.internal]]",
                    "  collect_memstats = false",
                    "[[processors.starlark]]",
                    '  script = "%s"' % script,
                    "",
                ]),
                encoding="utf-8",
            )
            proc = _run_telegraf(self.binary, config)
        text = proc.stdout + proc.stderr
        self.assertNotEqual(proc.returncode, 0, text)
        self.assertIn("does not support while loops", text)

    def test_normalize_star_loads_and_splits_the_radio_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.influx"
            sample.write_text(
                "\n".join([
                    "ie_wlc_radio,index=1.2.3.4.5.6.2,wlc=lab,site=hq noise=10i",
                    "ie_wlc_radio,index=10.20.30.40.50.60.7.99,wlc=lab,site=hq channel=36i",
                    "ie_wlc_radio,index=9.8.7,wlc=lab,site=hq channel=1i",
                    "ie_wlc_client_raw,wlc=lab,site=hq,ap_name=AP-1,ms_mac_address=aabbccddeeff most_recent_rssi=-62i,most_recent_snr=28i",
                    "ie_wlc_rogue_raw,index=aabb,wlc=lab value=1i",
                    "",
                ]),
                encoding="utf-8",
            )
            emit = root / "emit.sh"
            emit.write_text("#!/bin/sh\ncat %s\n" % sample, encoding="utf-8")
            emit.chmod(0o755)
            config = root / "telegraf.conf"
            config.write_text(
                "\n".join([
                    "[agent]",
                    '  interval = "10s"',
                    "  omit_hostname = true",
                    "[[inputs.exec]]",
                    '  commands = ["%s"]' % emit,
                    '  data_format = "influx"',
                    '  timeout = "5s"',
                    "[[processors.starlark]]",
                    '  script = "%s"' % (WLC / "normalize.star"),
                    "",
                ]),
                encoding="utf-8",
            )
            proc = _run_telegraf(self.binary, config)
        text = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, text)
        for marker in DIALECT_MARKERS:
            self.assertNotIn(marker, text)
        self.assertIn("ap=1.2.3.4.5.6", text)
        self.assertIn("radio=2,", text)
        self.assertIn("ap=10.20.30.40.50.60", text)
        self.assertIn("radio=7,", text)
        self.assertIn("ap=9.8.7", text)
        self.assertIn("radio=0,", text)
        self.assertIn("ie_wlc_client_radio", text)
        self.assertIn("clients=1", text)
        self.assertIn("ie_wlc_client", text)
        self.assertIn("client=aabbccddeeff", text)
        self.assertIn("ie_wlc_rogue", text)
        self.assertIn("aps=1", text)

    def test_host_api_and_syslog_configs_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "api": 19273,
                "host": 19274,
                "syslog": 19275,
            }
            for name, port in cases.items():
                source = ROOT / "config" / "telegraf" / name / "telegraf.conf"
                text = source.read_text(encoding="utf-8")
                text = text.replace('listen = ":9273"', 'listen = ":%d"' % port)
                text = text.replace("udp://:6514", "udp://:%d" % (port + 100))
                text = text.replace("tcp://:6514", "tcp://:%d" % (port + 101))
                dest = root / ("%s.conf" % name)
                dest.write_text(text, encoding="utf-8")
                proc = _run_telegraf(self.binary, dest, timeout=40)
                output = proc.stdout + proc.stderr
                for marker in DIALECT_MARKERS:
                    self.assertNotIn(marker, output, name)
                self.assertEqual(proc.returncode, 0, "%s\n%s" % (name, output[-2000:]))


if __name__ == "__main__":
    unittest.main()
