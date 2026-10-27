"""Validators. Subprocesses are argv lists (never shell=True). Missing tools fall back to a syntax check."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time

import yaml

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None


def _which(env_name: str, binary: str) -> str | None:
    override = os.environ.get(env_name)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    return shutil.which(binary)


def _run(argv: list[str], timeout: int = 60, env: dict | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return 124, "validator timed out"
    except OSError as exc:
        return 127, str(exc)
    text = (proc.stdout or b"").decode("utf-8", "replace") + (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, text[-8000:]


def _msg(severity: str, text: str, line: int | None = None) -> dict:
    m = {"severity": severity, "text": text}
    if line is not None:
        m["line"] = line
    return m


def _syntax(language: str, content: str) -> tuple[bool, list[dict], str]:
    try:
        if language in ("yaml", "yml"):
            yaml.safe_load(content)
            return True, [_msg("info", "YAML parsed")], "yaml syntax"
        if language == "json":
            json.loads(content)
            return True, [_msg("info", "JSON parsed")], "json syntax"
        if language == "toml":
            if tomllib is None:
                return False, [_msg("error", "tomllib is not available")], "toml syntax"
            tomllib.loads(content)
            return True, [_msg("info", "TOML parsed")], "toml syntax"
        if language == "python":
            compile(content, "<config>", "exec")
            return True, [_msg("info", "Python compiled")], "python syntax"
    except Exception as exc:  # parser errors are the result, not a crash
        return False, [_msg("error", "%s: %s" % (exc.__class__.__name__, exc))], language + " syntax"
    return True, [_msg("info", "no structured syntax check for this language; accepted as text")], "text"


def _prepare_prometheus(content: str, work: str, rules_text: str | None) -> str:
    """promtool follows rule_files paths. Point them at a temp copy so the live file is untouched."""
    os.makedirs(work, exist_ok=True)
    rules_path = os.path.join(work, "alert-rules.yml")
    if rules_text is None:
        rules_text = "groups: []\n"
    with open(rules_path, "w", encoding="utf-8") as fh:
        fh.write(rules_text)
    # certificates are not required for a syntax check; give promtool an empty file if referenced
    for cert_dir in ("certs", "ie-certs"):
        certs = os.path.join(work, cert_dir)
        os.makedirs(certs, exist_ok=True)
        open(os.path.join(certs, "ca.crt"), "a", encoding="utf-8").close()
    open(os.path.join(work, "netbox.token"), "a", encoding="utf-8").close()
    rewritten = (
        content.replace("/etc/prometheus/", work + "/")
        .replace("/etc/ie-certs/", os.path.join(work, "ie-certs") + "/")
        .replace("/run/secrets/netbox_token", os.path.join(work, "netbox.token"))
    )
    path = os.path.join(work, "prometheus.yml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(rewritten)
    return path


def validate_content(validator: str, language: str, content: str, sibling_rules: str | None = None) -> dict:
    """Return the contract validate payload. Never writes the live file."""
    started = time.monotonic()
    tool = validator or "syntax"
    ok = True
    messages: list[dict] = []

    def finish(ok_, messages_, tool_):
        return {
            "ok": ok_,
            "messages": messages_,
            "tool": tool_,
            "durationMs": int((time.monotonic() - started) * 1000),
        }

    if validator in ("yaml", "json", "toml", "python", "syntax", "text", ""):
        lang = language if validator in ("syntax", "text", "") else validator
        ok, messages, tool = _syntax(lang if validator not in ("syntax", "text", "") else language, content)
        return finish(ok, messages, tool)

    with tempfile.TemporaryDirectory(prefix="ie-validate-") as work:
        path = os.path.join(work, "candidate")
        if validator == "promtool":
            path = _prepare_prometheus(content, work, sibling_rules)
            binary = _which("PROMTOOL_BIN", "promtool")
            if not binary:
                ok, messages, tool = _syntax("yaml", content)
                messages.insert(0, _msg("warning", "promtool is not in this image; YAML syntax only"))
                return finish(ok, messages, "yaml syntax (promtool unavailable)")
            code, out = _run([binary, "check", "config", path])
            tool = "promtool check config"
        elif validator == "promtool-rules":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            binary = _which("PROMTOOL_BIN", "promtool")
            if not binary:
                ok, messages, tool = _syntax("yaml", content)
                messages.insert(0, _msg("warning", "promtool is not in this image; YAML syntax only"))
                return finish(ok, messages, "yaml syntax (promtool unavailable)")
            code, out = _run([binary, "check", "rules", path])
            tool = "promtool check rules"
        elif validator == "amtool":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            binary = _which("AMTOOL_BIN", "amtool")
            if not binary:
                ok, messages, tool = _syntax("yaml", content)
                messages.insert(0, _msg("warning", "amtool is not in this image; YAML syntax only"))
                return finish(ok, messages, "yaml syntax (amtool unavailable)")
            code, out = _run([binary, "check-config", path])
            tool = "amtool check-config"
        elif validator == "blackbox":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            binary = _which("BLACKBOX_BIN", "blackbox_exporter")
            if not binary:
                ok, messages, tool = _syntax("yaml", content)
                messages.insert(0, _msg("warning", "blackbox_exporter is not in this image; YAML syntax only"))
                return finish(ok, messages, "yaml syntax (blackbox_exporter unavailable)")
            code, out = _run([binary, "--config.check", "--config.file", path])
            tool = "blackbox_exporter --config.check"
        elif validator == "snmp":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            binary = _which("SNMP_EXPORTER_BIN", "snmp_exporter")
            if not binary:
                ok, messages, tool = _syntax("yaml", content)
                messages.insert(0, _msg("warning", "snmp_exporter is not in this image; YAML syntax only"))
                return finish(ok, messages, "yaml syntax (snmp_exporter unavailable)")
            env = dict(os.environ)
            env.setdefault("SNMP_V2_COMMUNITY", "syntax-check")
            env.setdefault("SNMP_V3_USER", "syntax-check")
            env.setdefault("SNMP_V3_USERNAME", env.get("SNMP_V3_USER", "syntax-check"))
            env.setdefault("SNMP_V3_AUTH_PASSWORD", "syntax-check")
            env.setdefault("SNMP_V3_PRIV_PASSWORD", "syntax-check")
            code, out = _run([binary, "--config.file", path, "--config.expand-environment-variables", "--dry-run"], env=env)
            tool = "snmp_exporter --dry-run"
        elif validator == "caddy":
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            binary = _which("CADDY_BIN", "caddy")
            if not binary:
                return finish(True, [_msg("warning", "caddy is not in this image; Caddyfile was not executed")], "caddy unavailable")
            code, out = _run([binary, "validate", "--config", path, "--adapter", "caddyfile"])
            tool = "caddy validate"
            # Certificate files exist only inside the Caddy container.
            if code != 0 and "/certs/" in out:
                return finish(True, [_msg("warning", "caddy validate complained only about certificate paths that exist in the caddy container")], tool)
        elif validator == "telegraf":
            ok, messages, tool = _syntax("toml", content)
            messages.insert(0, _msg("warning", "telegraf --test was not run: it contacts devices and the Docker socket. TOML syntax only."))
            return finish(ok, messages, "toml syntax (telegraf --test skipped)")
        elif validator == "python":
            ok, messages, tool = _syntax("python", content)
            return finish(ok, messages, tool)
        else:
            ok, messages, tool = _syntax(language, content)
            messages.insert(0, _msg("warning", "no dedicated validator %r; syntax check only" % validator))
            return finish(ok, messages, tool)

        ok = code == 0
        severity = "info" if ok else "error"
        text = (out or ("ok" if ok else "validator failed")).strip()
        messages = [_msg(severity, text[:4000])]
        return finish(ok, messages, tool)
