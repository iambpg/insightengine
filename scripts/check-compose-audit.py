#!/usr/bin/env python3
"""Static checks for docker-compose.yml that do not need a Docker daemon.

After YAML merge (anchors included):

- A volume target that is a strict child of another volume target on the same
  service fails when the parent is a read-only directory mount. Targets that
  still contain ``$`` are skipped (they nest only after compose interpolation).
- ``--web.enable-lifecycle`` is allowed only on the prometheus service, which
  must have it. Anchors are visible because PyYAML applies ``<<``.
- caddy, ie-config, and netbox must not depend on a netdisco service.
  The netdisco chain that can fail on its own is ``required: false``.
- Healthchecks must not request ``http://localhost`` (busybox wget uses ::1).
- netdisco-postgres must follow the upstream PG18 contract, and the NetBox
  service must mount module-map.yml at /etc/ie/module-map.yml.
- netbox/netbox_lists/__init__.py must export ``config`` for NetBox 4.x.

Exit 0 when every check passes. Exit 1 and print one line per problem.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("SKIP  PyYAML is not installed", file=sys.stderr)
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"

MODE_RE = re.compile(
    r"^(?:ro|rw|z|Z|nocopy|shared|rshared|slave|rslave|private|rprivate|"
    r"delegated|cached|consistent)"
    r"(?:,(?:ro|rw|z|Z|nocopy|shared|rshared|slave|rslave|private|rprivate|"
    r"delegated|cached|consistent))*$"
)
LIFECYCLE = "--web.enable-lifecycle"
OPTIONAL_DEPS = (
    ("netdisco-db-role", "netdisco-postgres"),
    ("netdisco-db-init", "netdisco-db-role"),
    ("netdisco-backend", "netdisco-db-init"),
    ("netdisco-web", "netdisco-db-init"),
    ("netdisco-scheduler", "netdisco-backend"),
)
CORE_NO_NETDISCO = ("caddy", "ie-config", "netbox")


def split_outside_braces(spec: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in spec:
        if ch == "{":
            depth += 1
            buf.append(ch)
        elif ch == "}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == ":" and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def parse_short(spec: str) -> tuple[str, str, str]:
    parts = split_outside_braces(spec.strip())
    if len(parts) >= 3 and MODE_RE.match(parts[-1]):
        return ":".join(parts[:-2]), parts[-2], parts[-1]
    if len(parts) == 1:
        return "", parts[0], ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[-1], ""


def mount_kind(source: str, root: Path) -> str:
    """dir, file, or unknown. Named volumes are directories."""
    if not source:
        return "dir"
    if "${" in source or source.startswith("$"):
        return "unknown"
    if "/" not in source and not source.startswith("."):
        return "dir"
    path = Path(source)
    if not path.is_absolute():
        path = root / source
    try:
        if path.is_dir():
            return "dir"
        if path.is_file():
            return "file"
    except OSError:
        # An installed tree can have root-owned mode 400 secrets. Stat failing
        # must not crash the audit.
        return "unknown"
    if "." in path.name:
        return "file"
    return "dir"


def is_strict_child(child: str, parent: str) -> bool:
    child = child.rstrip("/") or "/"
    parent = parent.rstrip("/") or "/"
    if parent == "/":
        return child != "/"
    return child.startswith(parent + "/")


def volume_mounts(service: dict, root: Path) -> list[dict]:
    mounts = []
    for item in service.get("volumes") or []:
        if isinstance(item, dict):
            source = str(item.get("source") or "")
            target = str(item.get("target") or "")
            mode = "ro" if item.get("read_only") else str(item.get("mode") or "")
        else:
            source, target, mode = parse_short(str(item))
        mounts.append(
            {
                "source": source,
                "target": target,
                "ro": "ro" in mode.split(","),
                "kind": mount_kind(source, root),
                "raw": item if isinstance(item, str) else target,
            }
        )
    return mounts


def command_text(service: dict) -> str:
    chunks: list[str] = []
    for key in ("command", "entrypoint"):
        value = service.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            chunks.extend(str(part) for part in value)
        else:
            chunks.append(str(value))
    return "\n".join(chunks)


def depends(service: dict) -> dict[str, dict]:
    raw = service.get("depends_on") or {}
    if isinstance(raw, list):
        return {str(name): {"required": True} for name in raw}
    if isinstance(raw, dict):
        out = {}
        for name, spec in raw.items():
            if isinstance(spec, dict):
                # Missing means required. Boolean false is the only optional form we emit.
                out[str(name)] = {"required": spec.get("required", True) is not False}
            else:
                out[str(name)] = {"required": True}
        return out
    return {}


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_strings(item)
    elif isinstance(obj, dict):
        for item in obj.values():
            yield from walk_strings(item)


def nesting_errors(services: dict, root: Path) -> list[str]:
    errors = []
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        mounts = [m for m in volume_mounts(service, root) if "$" not in m["target"]]
        parents = [m for m in mounts if m["ro"] and m["kind"] == "dir"]
        for child in mounts:
            for parent in parents:
                if child is parent:
                    continue
                if is_strict_child(child["target"], parent["target"]):
                    errors.append(
                        f"{name}: {child['target']} is mounted under read-only {parent['target']}"
                    )
    return errors


def lifecycle_errors(services: dict) -> list[str]:
    errors = []
    if "prometheus" not in services:
        errors.append("prometheus service is missing --web.enable-lifecycle")
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        has = LIFECYCLE in command_text(service)
        if name == "prometheus" and not has:
            errors.append("prometheus is missing --web.enable-lifecycle")
        if name != "prometheus" and has:
            errors.append(f"{name}: --web.enable-lifecycle is Prometheus-only")
    return errors


def dependency_errors(services: dict) -> list[str]:
    errors = []
    for name in CORE_NO_NETDISCO:
        service = services.get(name)
        if not isinstance(service, dict):
            continue
        for dep in depends(service):
            if dep == "netdisco-postgres" or dep.startswith("netdisco-"):
                errors.append(f"{name} depends_on {dep}; a Netdisco failure must not block it")
    if "netdisco-postgres" not in services:
        return errors
    for service_name, dep_name in OPTIONAL_DEPS:
        service = services.get(service_name)
        if not isinstance(service, dict):
            errors.append(f"{service_name} is missing")
            continue
        info = depends(service).get(dep_name)
        if info is None:
            errors.append(f"{service_name} does not depend on {dep_name}")
        elif info["required"]:
            errors.append(f"{service_name} depends_on {dep_name} is required; set required: false")
    return errors


def health_errors(services: dict) -> list[str]:
    errors = []
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        for text in walk_strings(service.get("healthcheck")):
            if "http://localhost" in text:
                errors.append(f"{name}: healthcheck uses http://localhost ({text})")
    return errors


def netdisco_errors(services: dict, root: Path) -> list[str]:
    errors = []
    pg = services.get("netdisco-postgres")
    if not isinstance(pg, dict):
        return errors
    env = pg.get("environment") or {}
    if not isinstance(env, dict):
        errors.append("netdisco-postgres environment is not a mapping")
        env = {}
    for key in (
        "NETDISCO_CURRENT_PG_VERSION",
        "NETDISCO_DB_SUPERUSER",
        "NETDISCO_DB_NAME",
        "NETDISCO_DB_USER",
        "NETDISCO_DB_PASS",
    ):
        if key not in env:
            errors.append(f"netdisco-postgres is missing {key}")
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "PGHOST", "PGUSER", "PGPASSWORD"):
        if key in env:
            errors.append(f"netdisco-postgres must not set {key}")
    targets = [m["target"] for m in volume_mounts(pg, root)]
    if "/var/lib/postgresql" not in targets:
        errors.append("netdisco-postgres volume must be mounted at /var/lib/postgresql")
    if any(t.rstrip("/") in ("/var/lib/postgresql/data", "/var/lib/postgresql/netdisco-pgdata") for t in targets):
        errors.append("netdisco-postgres still uses the old PGDATA mount")
    for name in ("netdisco-db-init", "netdisco-backend", "netdisco-web"):
        service = services.get(name) or {}
        service_env = service.get("environment") or {}
        if isinstance(service_env, dict):
            for key in ("NETDISCO_DB_PASS", "NETDISCO_DB_USER", "NETDISCO_DB_NAME", "PGHOST"):
                if key not in service_env:
                    errors.append(f"{name} is missing {key}")
    ie = services.get("ie-config") or {}
    ie_env = ie.get("environment") or {}
    url = ""
    if isinstance(ie_env, dict):
        url = str(ie_env.get("NETDISCO_DATABASE_URL") or "")
    if "NETDISCO_DB_PASSWORD" not in url or "netdisco-postgres" not in url:
        errors.append("ie-config NETDISCO_DATABASE_URL must use NETDISCO_DB_PASSWORD and netdisco-postgres")
    return errors


def module_map_errors(services: dict, root: Path) -> list[str]:
    errors = []
    for name in ("netbox", "netbox-worker"):
        service = services.get(name)
        if not isinstance(service, dict):
            errors.append(f"{name} service is missing")
            continue
        targets = [m["target"] for m in volume_mounts(service, root)]
        if "/etc/ie/module-map.yml" not in targets:
            errors.append(f"{name} does not mount module-map.yml at /etc/ie/module-map.yml")
    return errors


def caddy_sni_errors(root: Path) -> list[str]:
    """default_sni covers every public TLS site. scrape-lb is HTTP only."""
    errors = []
    main = root / "config/caddy/Caddyfile"
    scrape = root / "config/caddy/Caddyfile.scrape-lb"
    if not main.is_file():
        return ["config/caddy/Caddyfile is missing"]
    text = main.read_text()
    if "default_sni {$PUBLIC_HOST}" not in text:
        errors.append("Caddyfile must set default_sni {$PUBLIC_HOST} for IP clients that send no SNI")
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if code.startswith("fallback_sni"):
            errors.append("Caddyfile must not use fallback_sni; that applies only when SNI is present")
        if code.startswith("https://") and "{$PUBLIC_HOST}" not in code and not code.startswith("https://caddy:"):
            errors.append(f"TLS site is not PUBLIC_HOST or the internal caddy name: {code}")
    if scrape.is_file() and "https://" in scrape.read_text():
        errors.append("scrape-lb Caddyfile serves TLS; it needs default_sni or it must stay HTTP")
    return errors


def plugin_errors(root: Path) -> list[str]:
    errors = []
    init_path = root / "netbox/netbox_lists/__init__.py"
    apps_path = root / "netbox/netbox_lists/apps.py"
    urls_path = root / "netbox/netbox_lists/api/urls.py"
    views_path = root / "netbox/netbox_lists/api/views.py"
    for path in (init_path, apps_path, urls_path, views_path):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(root)}")
    if errors:
        return errors
    init = ast.parse(init_path.read_text())
    exported = False
    for node in init.body:
        if isinstance(node, ast.ImportFrom) and node.module == "apps":
            names = {alias.name for alias in node.names}
            if {"ListsConfig", "config"} <= names:
                exported = True
    if not exported:
        errors.append("netbox_lists/__init__.py must import config from .apps")
    apps = ast.parse(apps_path.read_text())
    subclass = False
    assigned = False
    imported = False
    for node in apps.body:
        if isinstance(node, ast.ImportFrom) and node.module == "netbox.plugins":
            if any(alias.name == "PluginConfig" for alias in node.names):
                imported = True
        if isinstance(node, ast.ClassDef) and node.name == "ListsConfig":
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "PluginConfig":
                    subclass = True
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "config":
                    if isinstance(node.value, ast.Name) and node.value.id == "ListsConfig":
                        assigned = True
    if not imported:
        errors.append("ListsConfig must subclass netbox.plugins.PluginConfig")
    if not subclass:
        errors.append("ListsConfig is not a PluginConfig subclass")
    if not assigned:
        errors.append("apps.py must set config = ListsConfig")
    urls = urls_path.read_text()
    if "prometheus-devices/" not in urls:
        errors.append("api/urls.py is missing the prometheus-devices route")
    views = views_path.read_text()
    for needle in ("from dcim.models import Device", "primary_ip4", "role__slug", "custom_field_data"):
        if needle not in views:
            errors.append(f"api/views.py is missing {needle}")
    if "device_role" in views:
        errors.append("api/views.py still uses device_role; NetBox 4.6 Device.role is the field")
    sd = (root / "netbox/netbox_lists/sd.py").read_text()
    if "/etc/ie/module-map.yml" not in sd:
        errors.append("sd.py default map path is not /etc/ie/module-map.yml")
    return errors


def audit(data: dict, root: Path, *, full: bool) -> list[str]:
    services = data.get("services") or {}
    errors = []
    errors.extend(nesting_errors(services, root))
    errors.extend(lifecycle_errors(services))
    errors.extend(dependency_errors(services))
    errors.extend(health_errors(services))
    if full:
        errors.extend(netdisco_errors(services, root))
        errors.extend(module_map_errors(services, root))
        errors.extend(postgres17_volume_errors(services, root))
        errors.extend(stack_fix_errors(services))
    return errors


def postgres17_volume_errors(services: dict, root: Path) -> list[str]:
    """postgres:17 keeps the cluster in the image VOLUME /var/lib/postgresql/data."""
    errors = []
    for name in ("netbox-postgres", "insightengine-postgres"):
        service = services.get(name)
        if not isinstance(service, dict):
            continue
        env = service.get("environment") or {}
        if not isinstance(env, dict) or env.get("PGDATA") != "/var/lib/postgresql/data/pgdata":
            errors.append(f"{name} must set PGDATA=/var/lib/postgresql/data/pgdata")
        targets = [mount["target"] for mount in volume_mounts(service, root)]
        if "/var/lib/postgresql/data" not in targets:
            errors.append(f"{name} must mount its named volume at /var/lib/postgresql/data")
        if "/var/lib/postgresql" in targets:
            errors.append(f"{name} must not mount the parent path /var/lib/postgresql")
    active = services.get("activepieces-postgres")
    if isinstance(active, dict):
        targets = [mount["target"] for mount in volume_mounts(active, root)]
        env = active.get("environment") or {}
        if "/var/lib/postgresql/data" not in targets:
            errors.append("activepieces-postgres must keep its volume at /var/lib/postgresql/data")
        if isinstance(env, dict) and env.get("PGDATA"):
            errors.append("activepieces-postgres must not set PGDATA; existing data is at the volume root")
    return errors


def stack_fix_errors(services: dict) -> list[str]:
    errors = []
    netbox = services.get("netbox") if isinstance(services.get("netbox"), dict) else {}
    health = netbox.get("healthcheck") or {}
    if health.get("start_period") != "900s":
        errors.append("netbox healthcheck start_period must be 900s")
    env = netbox.get("environment") or {}
    if isinstance(env, dict) and "SUPERUSER_API_KEY" not in env:
        errors.append("netbox must pass SUPERUSER_API_KEY")
    worker = services.get("netbox-worker") if isinstance(services.get("netbox-worker"), dict) else {}
    if worker.get("pull_policy") != "never":
        errors.append("netbox-worker pull_policy must be never")
    types = services.get("netbox-device-types")
    if not isinstance(types, dict):
        errors.append("netbox-device-types service is missing")
    else:
        if types.get("restart") != "no":
            errors.append("netbox-device-types must not restart")
        if types.get("pull_policy") != "never":
            errors.append("netbox-device-types pull_policy must be never")
        info = depends(types).get("netbox")
        if not info or info.get("required"):
            errors.append("netbox-device-types must depend on netbox with required: false")
        for name, service in services.items():
            if name == "netbox-device-types" or not isinstance(service, dict):
                continue
            if "netbox-device-types" in depends(service):
                errors.append(f"{name} must not wait on netbox-device-types")
    for name in ("netdisco-backend", "netdisco-web", "netdisco-scheduler"):
        service = services.get(name) or {}
        service_env = service.get("environment") or {}
        if isinstance(service_env, dict) and service_env.get("DANCER_ENVDIR") != "/home/netdisco/nd-site-local":
            errors.append(f"{name} must set DANCER_ENVDIR=/home/netdisco/nd-site-local")
    return errors


def _load(text: str) -> dict:
    loaded = yaml.safe_load(text)
    return loaded if isinstance(loaded, dict) else {}


def self_test() -> list[str]:
    failures = []

    def expect(label: str, text: str, predicate) -> None:
        errors = audit(_load(text), Path("/tmp/ie-audit-missing"), full=False)
        if not predicate(errors):
            failures.append(f"self-test {label}: {errors}")

    expect(
        "nested ro mount",
        """
services:
  prometheus:
    image: x
    volumes:
      - ./config:/etc/prometheus:ro
      - ./ca.crt:/etc/prometheus/certs/ca.crt:ro
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: any("read-only" in e for e in errs),
    )
    expect(
        "rw parent file mount",
        """
services:
  cust-exporter:
    image: x
    volumes:
      - ./app:/app
      - ./netbox.token:/app/netbox.token:ro
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: not any("read-only" in e for e in errs),
    )
    expect(
        "lifecycle on alertmanager",
        """
services:
  alertmanager:
    image: x
    command: ["--web.enable-lifecycle"]
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: any("alertmanager" in e and "Prometheus-only" in e for e in errs),
    )
    expect(
        "lifecycle inherited from anchor",
        """
x-bad: &bad
  command: ["--web.enable-lifecycle"]
services:
  alertmanager:
    <<: *bad
    image: x
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: any(e.startswith("alertmanager:") for e in errs),
    )
    expect(
        "variable targets are not flagged",
        """
services:
  setup:
    image: x
    volumes:
      - ${INSTALL_DIR}:${INSTALL_DIR}
      - ${SETUP_OLD_STACK_ROOT:-/opt}:${SETUP_OLD_STACK_ROOT:-/opt}:ro
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: not any("setup:" in e for e in errs),
    )
    expect(
        "explicit volumes replace the anchor",
        """
x-a: &a
  volumes:
    - ./config:/etc/prometheus:ro
    - ./ca.crt:/etc/prometheus/certs/ca.crt:ro
services:
  prometheus:
    <<: *a
    image: p
    volumes:
      - ./config:/etc/prometheus:ro
      - ./ca.crt:/etc/ie-certs/ca.crt:ro
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: not any("read-only" in e for e in errs),
    )
    expect(
        "host root is not a parent of the socket",
        """
services:
  telegraf-host:
    image: x
    volumes:
      - /:/hostfs:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: not any("telegraf-host" in e for e in errs),
    )
    expect(
        "localhost healthcheck",
        """
services:
  caddy:
    image: x
    healthcheck:
      test: ["CMD", "wget", "http://localhost:2019/config/"]
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: any("http://localhost" in e for e in errs),
    )
    expect(
        "core service waiting on netdisco",
        """
services:
  caddy:
    image: x
    depends_on:
      netdisco-postgres: {condition: service_healthy}
  prometheus:
    image: p
    command: ["--web.enable-lifecycle"]
""",
        lambda errs: any("caddy depends_on netdisco-postgres" in e for e in errs),
    )
    bad_pg = postgres17_volume_errors(
        {
            "netbox-postgres": {
                "environment": {},
                "volumes": ["netbox-postgres-data:/var/lib/postgresql"],
            }
        },
        Path("/tmp/ie-audit-missing"),
    )
    if not any("PGDATA" in item or "/var/lib/postgresql/data" in item for item in bad_pg):
        failures.append(f"self-test postgres volume: {bad_pg}")
    locked = Path("/tmp/ie-audit-locked")
    if locked.exists():
        import shutil
        shutil.rmtree(locked, ignore_errors=True)
    locked.mkdir()
    secret = locked / "token"
    secret.write_text("x", encoding="utf-8")
    os.chmod(locked, 0)
    try:
        kind = mount_kind(str(secret), Path("/"))
    finally:
        os.chmod(locked, 0o755)
        import shutil
        shutil.rmtree(locked, ignore_errors=True)
    if os.geteuid() != 0 and kind != "unknown":
        failures.append(f"self-test mount_kind permission: {kind}")
    plugin_bad = plugin_errors(Path("/tmp/ie-audit-missing"))
    if not plugin_bad:
        failures.append("self-test plugin: missing tree was accepted")
    return failures


def main() -> int:
    failures = self_test()
    if not COMPOSE.is_file():
        print("FAIL  docker-compose.yml is missing")
        return 1
    data = yaml.safe_load(COMPOSE.read_text())
    if not isinstance(data, dict):
        print("FAIL  docker-compose.yml did not parse as a mapping")
        return 1
    services = data.get("services") or {}
    errors = audit(data, ROOT, full=True)
    errors.extend(plugin_errors(ROOT))
    errors.extend(caddy_sni_errors(ROOT))
    names = ", ".join(sorted(services))
    print(f"checked {len(services)} services: {names}")
    for item in failures:
        print(f"FAIL  {item}")
    for item in errors:
        print(f"FAIL  {item}")
    if failures or errors:
        return 1
    print("PASS  compose audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
