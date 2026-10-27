"""App registry. File ids map only to entries in apps.yml. Arbitrary paths are rejected."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class FileSpec:
    id: str
    path: str  # relative to config root
    label: str
    language: str
    editable: bool
    secret_file: bool
    read_only_reason: str
    validator: str
    has_secrets: bool


@dataclass
class ActionSpec:
    id: str
    label: str
    kind: str
    dangerous: bool
    roles: list[str]
    http: list[dict] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)


@dataclass
class AppSpec:
    id: str
    name: str
    description: str
    group: str
    sensitive: bool
    container: str
    containers: list[str]
    version: str
    ui_url: str
    files: list[FileSpec]
    actions: list[ActionSpec]

    def file(self, file_id: str) -> FileSpec | None:
        for f in self.files:
            if f.id == file_id:
                return f
        return None

    def action(self, action_id: str) -> ActionSpec | None:
        for a in self.actions:
            if a.id == action_id:
                return a
        return None


def _expand(value: str, env: dict[str, str]) -> str:
    if not isinstance(value, str):
        return value

    def repl(m):
        return env.get(m.group(1), "")

    return re.sub(r"\$\{([A-Z0-9_]+)\}", repl, value)


def _env() -> dict[str, str]:
    return dict(os.environ)


class Registry:
    def __init__(self, apps: list[AppSpec], config_root: str):
        self.apps = apps
        self.by_id = {a.id: a for a in apps}
        self.config_root = os.path.realpath(config_root)

    def get(self, app_id: str) -> AppSpec | None:
        if not _ID.match(app_id or ""):
            return None
        return self.by_id.get(app_id)

    def resolve(self, spec: FileSpec) -> str:
        """Absolute path for a registry file. Raises ValueError if it escapes the root."""
        rel = spec.path
        if not rel or rel.startswith("/") or "\x00" in rel:
            raise ValueError("refusing absolute path")
        parts = rel.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise ValueError("refusing path traversal")
        full = os.path.realpath(os.path.join(self.config_root, *parts))
        root = self.config_root
        if full != root and not full.startswith(root + os.sep):
            raise ValueError("path escapes config root")
        return full


def load_registry(path: str, config_root: str, env: dict[str, str] | None = None) -> Registry:
    env = env if env is not None else _env()
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    apps: list[AppSpec] = []
    seen: set[str] = set()
    for item in raw.get("apps") or []:
        app_id = item["id"]
        if app_id in seen or not _ID.match(app_id):
            raise ValueError("bad or duplicate app id %r" % app_id)
        seen.add(app_id)
        files = []
        file_ids: set[str] = set()
        for f in item.get("files") or []:
            fid = f["id"]
            if fid in file_ids or "/" in fid or ".." in fid or not re.match(r"^[A-Za-z0-9_.:-]{1,128}$", fid):
                raise ValueError("bad file id %s/%s" % (app_id, fid))
            file_ids.add(fid)
            files.append(FileSpec(
                id=fid,
                path=_expand(f["path"], env),
                label=f.get("label") or fid,
                language=f.get("language") or "text",
                editable=bool(f.get("editable", False)),
                secret_file=bool(f.get("secret_file", False)),
                read_only_reason=f.get("read_only_reason") or "",
                validator=f.get("validator") or "syntax",
                has_secrets=bool(f.get("has_secrets", False) or f.get("secret_file", False)),
            ))
        actions = []
        for a in item.get("actions") or []:
            http = []
            for h in a.get("http") or []:
                expanded = {}
                for key, value in h.items():
                    expanded[key] = _expand(value, env) if isinstance(value, str) else value
                http.append(expanded)
            actions.append(ActionSpec(
                id=a["id"],
                label=a.get("label") or a["id"],
                kind=a.get("kind") or "reload",
                dangerous=bool(a.get("dangerous", False)),
                roles=list(a.get("roles") or []),
                http=http,
                containers=[_expand(c, env) for c in (a.get("containers") or [])],
            ))
        primary = _expand(item.get("container") or "", env)
        containers = [_expand(c, env) for c in (item.get("containers") or [])]
        if primary and primary not in containers:
            containers.insert(0, primary)
        apps.append(AppSpec(
            id=app_id,
            name=item.get("name") or app_id,
            description=item.get("description") or "",
            group=item.get("group") or "platform",
            sensitive=bool(item.get("sensitive", False)),
            container=primary,
            containers=containers,
            version=_expand(item.get("version") or "", env),
            ui_url=_expand(item.get("ui_url") or "", env),
            files=files,
            actions=actions,
        ))
    return Registry(apps, config_root)
