"""Auth-map change detection, Prometheus rediscovery, and exporter reload targets."""

import logging
import socket
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from ie_config.snmp_profiles import validate_profile
from ie_config.snmp_sync import (
    auth_map_generation,
    bump_http_sd_generation,
    default_exporter_urls,
    host_resolves,
    iter_resolved,
    refresh_prometheus_http_sd,
    reload_exporters,
    sync_snmp,
    write_outputs,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = {
    "version": "3",
    "port": 161,
    "security_name": "mon-user",
    "security_level": "authPriv",
    "auth_protocol": "SHA",
    "auth_passphrase": "auth-secret-value",
    "priv_protocol": "AES",
    "priv_passphrase": "priv-secret-value",
}


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _rows(profile):
    return iter_resolved(
        [{"id": 7, "name": "sw", "primary_ip4": "10.9.9.9", "config_context": {"monitoring_snmp": profile}}],
        {},
        {},
    )


def test_auth_map_change_is_detected_and_a_repeat_is_not(tmp_path):
    base = tmp_path / "snmp.yml"
    base.write_text("auths: {}\nmodules: {}\n", encoding="utf-8")
    profile = validate_profile(EXAMPLE)
    first = write_outputs(str(tmp_path), str(base), _rows(profile))
    assert first["auth_map_changed"] is True
    assert first["mapped"] == 1
    assert len(first["auth_map_generation"]) == 12
    second = write_outputs(str(tmp_path), str(base), _rows(profile))
    assert second["auth_map_changed"] is False
    assert second["auth_map_generation"] == first["auth_map_generation"]
    other = validate_profile(dict(EXAMPLE, auth_passphrase="other-auth-secret"))
    third = write_outputs(str(tmp_path), str(base), _rows(other))
    assert third["auth_map_changed"] is True
    assert third["auth_map_generation"] != first["auth_map_generation"]
    assert auth_map_generation({"10.9.9.9": "a"}) == auth_map_generation({"10.9.9.9": "a"})


def test_bump_rewrites_every_snmp_token_and_leaves_the_rest(tmp_path):
    text = (
        "url: https://caddy:8443/prometheus-devices/?status=active&role=access-switch\n"
        "url: https://caddy:8443/prometheus-devices/?status=active&role=access-switch&ie_sd=0\n"
        "url: https://caddy:8443/prometheus-devices/?status=active&ie_sd=0\n"
    )
    updated = bump_http_sd_generation(text, "abc123")
    assert updated.count("ie_sd=abc123") == 2
    assert "ie_sd=0" not in updated
    assert "role=access-switch\n" in updated
    assert bump_http_sd_generation("url: https://caddy/no-token\n", "abc") is None
    with pytest.raises(ValueError):
        bump_http_sd_generation(text, "not a token")


def test_shipped_snmp_jobs_refresh_every_minute_and_icmp_jobs_do_not():
    text = (ROOT / "config" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    jobs = text.split("\n  - job_name: ")
    snmp = [job for job in jobs if job.startswith("snmp-") and not job.startswith("snmp-exporter")]
    icmp = [job for job in jobs if job.startswith("icmp-")]
    assert len(snmp) == 8
    assert icmp
    for job in snmp:
        assert "refresh_interval: 1m" in job
        assert "ie_sd=0" in job
    for job in icmp:
        assert "ie_sd=" not in job
        assert "refresh_interval: 1m" not in job
    exporter = next(job for job in jobs if job.startswith("snmp-exporter"))
    assert "ie_sd=" not in exporter
    assert "http_sd_configs" not in exporter
    bumped = bump_http_sd_generation(text, "abc123abc123")
    assert bumped.count("ie_sd=abc123abc123") == 8
    assert "ie_sd=0" not in bumped
    assert bumped.split("ie_sd=")[0] == text.split("ie_sd=")[0]


def test_refresh_bumps_the_file_and_reloads_prometheus(tmp_path):
    prom = tmp_path / "config" / "prometheus"
    prom.mkdir(parents=True)
    path = prom / "prometheus.yml"
    path.write_text("url: http://sd:9/targets?ie_sd=0\n", encoding="utf-8")
    path.chmod(0o640)
    seen = []

    def opener(req, timeout=0):
        seen.append((req.full_url, req.get_method(), req.data, timeout))
        return _Resp()

    settings = SimpleNamespace(config_root=str(tmp_path), prometheus_url="http://prometheus:9090")
    assert refresh_prometheus_http_sd(settings, "abc123", opener) is True
    body = path.read_text(encoding="utf-8")
    assert body == "url: http://sd:9/targets?ie_sd=abc123\n"
    assert path.stat().st_mode & 0o777 == 0o640
    assert seen == [("http://prometheus:9090/-/reload", "POST", b"", 5)]
    assert refresh_prometheus_http_sd(settings, "abc123", opener) is True
    assert path.read_text(encoding="utf-8") == body
    assert len(seen) == 2


def test_refresh_failures_warn_and_do_not_raise(tmp_path, caplog):
    prom = tmp_path / "config" / "prometheus"
    prom.mkdir(parents=True)
    path = prom / "prometheus.yml"
    path.write_text("url: http://sd:9/targets?ie_sd=0\n", encoding="utf-8")
    settings = SimpleNamespace(config_root=str(tmp_path), prometheus_url="http://prometheus:9090")

    def refused(req, timeout=0):
        raise urllib.error.URLError("refused")

    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert refresh_prometheus_http_sd(settings, "abc123", refused) is False
    assert "prometheus reload failed" in caplog.text
    assert "ie_sd=abc123" in path.read_text(encoding="utf-8")

    caplog.clear()
    path.write_text("url: http://sd:9/targets\n", encoding="utf-8")
    seen = []
    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert refresh_prometheus_http_sd(settings, "abc123", lambda req, timeout=0: seen.append(req) or _Resp()) is False
    assert seen == []
    assert "ie_sd token missing" in caplog.text
    assert path.read_text(encoding="utf-8") == "url: http://sd:9/targets\n"

    caplog.clear()
    path.write_text("url: http://sd:9/targets?ie_sd=0\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert refresh_prometheus_http_sd(settings, "!!!", lambda req, timeout=0: _Resp()) is False
    assert "bad generation" in caplog.text
    assert path.read_text(encoding="utf-8").endswith("ie_sd=0\n")

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert refresh_prometheus_http_sd(settings, "abc123", lambda req, timeout=0: _Resp(503)) is False
    assert "status 503" in caplog.text


def test_missing_exporters_are_debug_and_scale_replicas_stay(monkeypatch, caplog):
    monkeypatch.delenv("SNMP_EXPORTER_RELOAD_URLS", raising=False)
    monkeypatch.delenv("SNMP_EXPORTER_REPLICAS", raising=False)

    def resolve(host):
        return host in ("snmp-exporter-1", "snmp-exporter-2")

    with caplog.at_level(logging.DEBUG, logger="ie.snmp"):
        urls = default_exporter_urls(resolve)
    assert urls == ["http://snmp-exporter-1:9116", "http://snmp-exporter-2:9116"]
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
    debug = [record.message for record in caplog.records if record.levelno == logging.DEBUG]
    assert any("snmp-exporter-3" in message for message in debug)
    assert any("snmp-exporter-4" in message for message in debug)

    monkeypatch.setenv("SNMP_EXPORTER_REPLICAS", "4")
    assert default_exporter_urls(lambda host: True) == [
        "http://snmp-exporter-%d:9116" % i for i in range(1, 5)
    ]
    monkeypatch.setenv("SNMP_EXPORTER_REPLICAS", "3")
    assert [url.split("/")[2].split(":")[0] for url in default_exporter_urls(lambda host: True)] == [
        "snmp-exporter-1", "snmp-exporter-2", "snmp-exporter-3",
    ]

    caplog.clear()
    monkeypatch.setenv("SNMP_EXPORTER_REPLICAS", "0")
    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert len(default_exporter_urls(lambda host: True)) == 4
    assert "SNMP_EXPORTER_REPLICAS is invalid" in caplog.text

    monkeypatch.setenv("SNMP_EXPORTER_RELOAD_URLS", "http://snmp-exporter-4:9116, http://kept:9116")
    assert default_exporter_urls(lambda host: host == "kept") == ["http://kept:9116"]


def test_dns_miss_skips_and_a_temporary_failure_keeps_the_url(monkeypatch):
    def nxdomain(*args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", nxdomain)
    assert host_resolves("snmp-exporter-3") is False

    def again(*args, **kwargs):
        raise socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")

    monkeypatch.setattr(socket, "getaddrinfo", again)
    assert host_resolves("snmp-exporter-1") is True
    assert host_resolves("") is False


def test_a_down_exporter_that_resolves_still_warns(caplog):
    def opener(req, timeout=0):
        raise urllib.error.URLError("refused")

    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        assert reload_exporters(["http://snmp-exporter-1:9116"], opener) == []
    assert "snmp exporter reload failed for http://snmp-exporter-1:9116: URLError" in caplog.text


def _settings(tmp_path):
    snmp = tmp_path / "snmp"
    snmp.mkdir()
    prom = tmp_path / "config" / "prometheus"
    prom.mkdir(parents=True)
    (prom / "prometheus.yml").write_text(
        "url: https://caddy:8443/api/plugins/lists/prometheus-devices/?status=active&role=access-switch&ie_sd=0\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        config_root=str(tmp_path),
        snmp_dir=str(snmp),
        prometheus_url="http://prometheus:9090",
    )


def _get_json(profile):
    def get_json(path):
        if path.startswith("/api/dcim/devices/?"):
            return {"results": [{"id": 7}], "next": ""}
        return {
            "id": 7,
            "name": "sw1",
            "primary_ip4": "10.9.9.9/32",
            "role": {"slug": "access-switch"},
            "config_context": {"monitoring_snmp": profile},
        }
    return get_json


def test_sync_reloads_prometheus_only_when_the_auth_map_changes(tmp_path, caplog, monkeypatch):
    monkeypatch.delenv("SNMP_EXPORTER_RELOAD_URLS", raising=False)
    monkeypatch.delenv("SNMP_EXPORTER_REPLICAS", raising=False)
    settings = _settings(tmp_path)
    seen = []

    def opener(req, timeout=0):
        seen.append(req.full_url)
        return _Resp()

    profile = validate_profile(EXAMPLE)
    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        first = sync_snmp(settings, get_json=_get_json(profile), opener=opener, resolve=lambda host: False)
    assert first["auth_map_changed"] is True
    assert seen == ["http://prometheus:9090/-/reload"]
    body = (tmp_path / "config" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    assert "ie_sd=%s" % first["auth_map_generation"] in body
    assert "snmp-exporter-3" not in caplog.text
    assert not caplog.records

    sync_snmp(settings, get_json=_get_json(profile), opener=opener, resolve=lambda host: host == "snmp-exporter-9")
    assert seen == ["http://prometheus:9090/-/reload"]

    other = validate_profile(dict(EXAMPLE, priv_passphrase="other-priv-secret"))
    second = sync_snmp(settings, get_json=_get_json(other), opener=opener, resolve=lambda host: False)
    assert second["auth_map_changed"] is True
    assert seen == ["http://prometheus:9090/-/reload", "http://prometheus:9090/-/reload"]
    updated = (tmp_path / "config" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    assert "ie_sd=%s" % second["auth_map_generation"] in updated
    assert first["auth_map_generation"] not in updated


def test_sync_survives_a_prometheus_reload_failure(tmp_path, caplog, monkeypatch):
    monkeypatch.delenv("SNMP_EXPORTER_RELOAD_URLS", raising=False)
    monkeypatch.delenv("SNMP_EXPORTER_REPLICAS", raising=False)
    settings = _settings(tmp_path)

    def opener(req, timeout=0):
        raise urllib.error.URLError("down")

    with caplog.at_level(logging.WARNING, logger="ie.snmp"):
        summary = sync_snmp(
            settings,
            get_json=_get_json(validate_profile(EXAMPLE)),
            opener=opener,
            resolve=lambda host: False,
        )
    assert summary["auth_map_changed"] is True
    assert "prometheus reload failed" in caplog.text
    assert "ie_sd=%s" % summary["auth_map_generation"] in (
        tmp_path / "config" / "prometheus" / "prometheus.yml"
    ).read_text(encoding="utf-8")
    assert (tmp_path / "snmp" / "auth-by-ip.yml").is_file()
