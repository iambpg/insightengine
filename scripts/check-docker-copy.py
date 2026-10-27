#!/usr/bin/env python3
"""Check that every local image build can see its COPY/ADD sources.

Parses docker-compose.yml build sections (context, dockerfile, additional_contexts)
and each Dockerfile those services build. A COPY/ADD source must exist inside the
build context a clean checkout would send, unless it comes from an image stage
(--from matching a FROM ... AS name, a stage index, or an image reference).

Named contexts (compose additional_contexts) are separate roots: COPY --from=<name>
is checked against that directory. Remote contexts (git/http) are skipped.

Exit 0 when every local build is consistent. Exit 1 and print one line per problem.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path


REQUIRED_SERVICES = {
    "setup": "setup",
    "ie-config": "config-api",
    "insightengine-ui": "ui",
    "alert-relay": "config/alert-relay",
    "cust-exporter": "cust-exporter",
    "trapd": "trapd",
    "netbox": "netbox",
}

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}")
BOOL_FLAGS = {"link", "parents"}
VALUE_FLAGS = {"from", "chown", "chmod", "exclude", "checksum", "mount"}


def strip_comment(line: str) -> str:
    out: list[str] = []
    quote = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def resolve_vars(value: str, env: dict[str, str]) -> str:
    prev = None
    current = value
    while prev != current:
        prev = current

        def repl(match: re.Match[str], cur_env: dict[str, str] = env) -> str:
            name, op, default = match.group(1), match.group(2), match.group(3)
            val = cur_env.get(name)
            if op is None:
                return val if val is not None else ""
            if op == ":-":
                return val if val else (default or "")
            if op == "-":
                return val if val is not None else (default or "")
            if op in (":?", "?"):
                return val if val else ""
            return match.group(0)

        current = VAR_RE.sub(repl, current)
    return current


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_builds(text: str) -> list[dict]:
    """Return build blocks from the services mapping. Stdlib only (no PyYAML)."""
    results: list[dict] = []
    in_services = False
    service = None
    in_build = False
    in_additional = False
    current: dict | None = None

    def finish() -> None:
        nonlocal current
        if current and current.get("context"):
            results.append(current)
        current = None

    for raw in text.splitlines():
        if raw.endswith("\r"):
            raw = raw[:-1]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = strip_comment(raw).strip()
        if not line:
            continue
        if indent == 0:
            in_services = line == "services:"
            in_build = False
            in_additional = False
            service = None
            if not in_services:
                finish()
            continue
        if not in_services:
            continue
        if indent == 2 and line.endswith(":") and not line.startswith(("-", "?", "*", "&")):
            finish()
            service = unquote(line[:-1].strip())
            in_build = False
            in_additional = False
            continue
        if service and indent == 4 and (line == "build:" or line.startswith("build:")):
            finish()
            val = unquote(line.split(":", 1)[1].strip()) if ":" in line else ""
            current = {
                "service": service,
                "context": val or None,
                "dockerfile": None,
                "additional_contexts": {},
            }
            in_build = not bool(val)
            in_additional = False
            continue
        if not in_build or current is None:
            if indent <= 4:
                in_build = False
                in_additional = False
            continue
        if indent <= 4:
            in_build = False
            in_additional = False
            continue
        if indent == 6:
            key, _, val = line.partition(":")
            key = key.strip()
            val = unquote(val.strip())
            in_additional = False
            if key == "context" and val:
                current["context"] = val
            elif key == "dockerfile" and val:
                current["dockerfile"] = val
            elif key == "additional_contexts" and not val:
                in_additional = True
            continue
        if in_additional and indent == 8 and ":" in line:
            key, _, val = line.partition(":")
            current["additional_contexts"][key.strip()] = unquote(val.strip())
    finish()
    return results


def logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r").rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.endswith("\\") and not line.endswith("\\\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        lines.append(strip_comment(buf).strip())
        buf = ""
    if buf.strip():
        lines.append(strip_comment(buf).strip())
    return [ln for ln in lines if ln]


def stage_names(lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        if not line.upper().startswith("FROM "):
            continue
        body = line.split(None, 1)[1].strip()
        while body.startswith("--"):
            token, _, body = body.partition(" ")
            body = body.strip()
            if "=" not in token:
                nxt, _, body = body.partition(" ")
                body = body.strip()
                if nxt.startswith("--"):
                    body = f"{nxt} {body}".strip()
        parts = body.split()
        if len(parts) >= 3 and parts[-2].upper() == "AS":
            names.append(parts[-1])
    return names


def parse_copy(line: str) -> tuple[str, tuple[str, list[str]]] | None:
    upper = line.upper()
    if upper.startswith("ONBUILD "):
        line = line.split(None, 1)[1]
        upper = line.upper()
    if not (upper.startswith("COPY ") or upper.startswith("ADD ") or upper in ("COPY", "ADD")):
        return None
    kind, _, rest = line.partition(" ")
    rest = rest.strip()
    from_name = None
    while rest.startswith("--"):
        if " " in rest:
            token, rest = rest.split(None, 1)
        else:
            token, rest = rest, ""
        rest = rest.strip()
        name, eq, val = token[2:].partition("=")
        name = name.lower()
        if not eq:
            if name in BOOL_FLAGS:
                continue
            if name in VALUE_FLAGS:
                if not rest:
                    raise ValueError(f"--{name} needs a value in: {line}")
                if " " in rest:
                    val, rest = rest.split(None, 1)
                else:
                    val, rest = rest, ""
                rest = rest.strip()
            else:
                continue
        if name == "from":
            from_name = val
    if not rest:
        raise ValueError(f"{kind} has no paths: {line}")
    if rest.startswith("["):
        try:
            args = json.loads(rest)
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad JSON {kind}: {rest}") from exc
        if not isinstance(args, list) or len(args) < 2:
            raise ValueError(f"bad JSON {kind}: {rest}")
        sources = [str(item) for item in args[:-1]]
    elif rest.startswith("<<"):
        return kind.upper(), (from_name, [])
    else:
        parts = shlex.split(rest)
        if len(parts) < 2:
            raise ValueError(f"{kind} needs a source and a destination: {line}")
        sources = parts[:-1]
    return kind.upper(), (from_name, sources)


def _to_regex(pattern: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


def _docker_match(pattern: str, path: str) -> bool:
    pattern = pattern.strip()
    if not pattern or pattern == ".":
        return False
    pattern = pattern.rstrip("/")
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    if not pattern:
        return False
    regex = _to_regex(pattern)
    if anchored or "/" in pattern:
        return re.fullmatch(regex, path) is not None
    return re.fullmatch(regex, path.split("/")[-1]) is not None


class DockerIgnore:
    def __init__(self, context: Path):
        self.patterns: list[tuple[bool, str]] = []
        path = context / ".dockerignore"
        if not path.is_file():
            return
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            pat = line[1:] if neg else line
            if pat:
                self.patterns.append((neg, pat))

    def ignored(self, rel: str) -> bool:
        rel = rel.strip("/")
        if not rel or rel == ".":
            return False
        parts = rel.split("/")
        for i in range(1, len(parts)):
            if self._excluded("/".join(parts[:i])):
                return True
        return self._excluded(rel)

    def _excluded(self, path: str) -> bool:
        excluded = False
        for neg, pat in self.patterns:
            if _docker_match(pat, path):
                excluded = not neg
        return excluded


def is_remote(context: str) -> bool:
    return "://" in context or context.startswith("git@")


def project_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def dockerfile_names(selected: Path) -> list[Path]:
    files = [selected]
    parent = selected.parent
    if not parent.is_dir():
        return files
    for extra in sorted(parent.iterdir()):
        if not extra.is_file():
            continue
        name = extra.name
        if extra == selected:
            continue
        if name == "Dockerfile" or name.startswith("Dockerfile."):
            files.append(extra)
    return files


def has_payload(path: Path, context: Path, ignore: DockerIgnore) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        try:
            rel = path.resolve().relative_to(context.resolve()).as_posix()
        except ValueError:
            return False
        return not ignore.ignored(rel)
    for dirpath, dirnames, filenames in os.walk(path):
        rel_dir = Path(dirpath).resolve().relative_to(context.resolve()).as_posix()
        if rel_dir not in (".", "") and ignore.ignored(rel_dir):
            dirnames[:] = []
            continue
        kept: list[str] = []
        for dirname in dirnames:
            child = dirname if rel_dir in (".", "") else f"{rel_dir}/{dirname}"
            if not ignore.ignored(child):
                kept.append(dirname)
        dirnames[:] = kept
        for filename in filenames:
            rel = filename if rel_dir in (".", "") else f"{rel_dir}/{filename}"
            if not ignore.ignored(rel):
                return True
    return False


def looks_like_image(name: str) -> bool:
    return ":" in name or "/" in name


def check_sources(
    kind: str,
    sources: list[str],
    context: Path,
    ignore: DockerIgnore,
    where: str,
    errors: list[str],
) -> int:
    checked = 0
    for source in sources:
        if source.startswith("<<") or source.startswith("http://") or source.startswith("https://"):
            continue
        if source.startswith("/") or ".." in Path(source).parts:
            errors.append(f"FAIL {where}: {kind} source {source!r} escapes the build context")
            continue
        normalized = source[2:] if source.startswith("./") else source
        if normalized in ("", "."):
            if not has_payload(context, context, ignore):
                errors.append(f"FAIL {where}: {kind} source {source!r} is empty in {context}")
            else:
                checked += 1
            continue
        if any(ch in normalized for ch in "*?["):
            matches = [m for m in context.glob(normalized) if has_payload(m, context, ignore)]
            if not matches:
                errors.append(
                    f"FAIL {where}: {kind} source {source!r} matches nothing in {context}"
                )
            else:
                checked += 1
            continue
        candidate = context / normalized
        if not candidate.exists() or not has_payload(candidate, context, ignore):
            errors.append(
                f"FAIL {where}: {kind} source {source!r} is not in build context {context}"
            )
        else:
            checked += 1
    return checked


def check_dockerfile(
    service: str,
    dockerfile: Path,
    context: Path,
    additional: dict[str, Path],
    errors: list[str],
) -> tuple[int, int]:
    where = f"{service} ({dockerfile})"
    if not dockerfile.is_file():
        errors.append(f"FAIL {where}: Dockerfile is missing")
        return 0, 0
    if not context.is_dir():
        errors.append(f"FAIL {where}: build context does not exist: {context}")
        return 0, 0
    lines = logical_lines(dockerfile.read_text(encoding="utf-8", errors="replace"))
    stages = set(stage_names(lines))
    ignore = DockerIgnore(context)
    context_copies = 0
    stage_copies = 0
    for line in lines:
        try:
            parsed = parse_copy(line)
        except ValueError as exc:
            errors.append(f"FAIL {where}: {exc}")
            continue
        if parsed is None:
            continue
        kind, (from_name, sources) = parsed
        if not sources:
            continue
        if from_name is None:
            context_copies += check_sources(kind, sources, context, ignore, where, errors)
            continue
        if from_name in additional:
            named = additional[from_name]
            if not named.is_dir():
                errors.append(
                    f"FAIL {where}: additional context {from_name!r} does not exist: {named}"
                )
                continue
            rooted = [src.lstrip("/") for src in sources]
            context_copies += check_sources(
                kind, rooted, named, DockerIgnore(named), f"{where} --from={from_name}", errors
            )
            continue
        if from_name in stages or from_name.isdigit() or looks_like_image(from_name):
            stage_copies += len(sources)
            continue
        errors.append(
            f"FAIL {where}: {kind} --from={from_name} is not a build stage or an additional_contexts entry"
        )
    return context_copies, stage_copies


def load_builds(root: Path, env: dict[str, str]) -> tuple[list[dict], list[str]]:
    compose = root / "docker-compose.yml"
    if not compose.is_file():
        return [], [f"FAIL {compose}: compose file is missing"]
    builds = parse_builds(compose.read_text(encoding="utf-8", errors="replace"))
    errors: list[str] = []
    seen = {item["service"] for item in builds}
    for service, rel in REQUIRED_SERVICES.items():
        if service not in seen:
            errors.append(f"FAIL {service}: no local build block found in docker-compose.yml")
            continue
        match = next(item for item in builds if item["service"] == service)
        ctx = resolve_vars(match["context"], env)
        if is_remote(ctx):
            errors.append(f"FAIL {service}: expected a local build context, got {ctx}")
            continue
        got = project_path(root, ctx)
        expect = (root / rel).resolve()
        if got != expect:
            errors.append(f"FAIL {service}: build context is {got}, expected {expect}")
    return builds, errors


def check_root(root: Path, env: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    env = os.environ if env is None else env
    builds, errors = load_builds(root, env)
    notes: list[str] = []
    for build in builds:
        service = build["service"]
        context_value = resolve_vars(build["context"], env)
        if is_remote(context_value):
            notes.append(f"skip {service}: remote build context")
            continue
        context = project_path(root, context_value)
        dockerfile_value = build.get("dockerfile") or "Dockerfile"
        dockerfile_value = resolve_vars(dockerfile_value, env) or "Dockerfile"
        selected = dockerfile_value if Path(dockerfile_value).is_absolute() else context / dockerfile_value
        selected = Path(selected)
        additional = {
            name: project_path(root, resolve_vars(path, env))
            for name, path in build["additional_contexts"].items()
        }
        for dockerfile in dockerfile_names(selected):
            copies, stages = check_dockerfile(service, dockerfile, context, additional, errors)
            if not any(err.startswith(f"FAIL {service} ({dockerfile})") for err in errors):
                notes.append(
                    f"ok {service} ({dockerfile.relative_to(root) if dockerfile.is_relative_to(root) else dockerfile}): "
                    f"{copies} context COPY/ADD source(s), {stages} from image stages"
                )
    return errors, notes


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "svc").mkdir()
        (root / "svc" / "app.py").write_text("print(1)\n", encoding="utf-8")
        (root / "svc" / "Dockerfile").write_text(
            "FROM alpine AS build\n"
            "COPY app.py /app/app.py\n"
            "COPY --from=build /out/app /out/app\n"
            "COPY --chown=1:1 missing.py /nope\n",
            encoding="utf-8",
        )
        (root / "svc" / ".dockerignore").write_text("*.md\n!README.md\nsecret.txt\n", encoding="utf-8")
        (root / "svc" / "README.md").write_text("hi\n", encoding="utf-8")
        (root / "svc" / "skip.md").write_text("x\n", encoding="utf-8")
        (root / "svc" / "secret.txt").write_text("nope\n", encoding="utf-8")
        (root / "cfg").mkdir()
        (root / "cfg" / "plugins.py").write_text("PLUGINS = []\n", encoding="utf-8")
        (root / "nb").mkdir()
        (root / "nb" / "lists").mkdir()
        (root / "nb" / "lists" / "__init__.py").write_text("", encoding="utf-8")
        (root / "nb" / "Dockerfile").write_text(
            "FROM alpine\n"
            "COPY lists /opt/lists\n"
            "COPY --from=netbox_config plugins.py /etc/plugins.py\n",
            encoding="utf-8",
        )
        (root / "ui").mkdir()
        (root / "ui" / "package.json").write_text("{}\n", encoding="utf-8")
        (root / "ui" / "Dockerfile").write_text(
            "FROM node AS build\nCOPY package.json ./\nCOPY --from=build /app/out ./out\n",
            encoding="utf-8",
        )
        (root / "ui" / "Dockerfile.placeholder").write_text(
            "FROM nginx\nCOPY placeholder/index.html /html/index.html\n",
            encoding="utf-8",
        )
        (root / "ui" / "placeholder").mkdir()
        (root / "ui" / "placeholder" / "index.html").write_text("ok\n", encoding="utf-8")
        compose = """
services:
  svc:
    build:
      context: ./svc
      dockerfile: Dockerfile
  nb:
    build:
      context: ./nb
      additional_contexts:
        netbox_config: ./cfg
  ui:
    build:
      context: ./ui
      dockerfile: ${IE_UI_DOCKERFILE:-Dockerfile}
  remote:
    build:
      context: https://example.invalid/repo.git#v1
"""
        (root / "docker-compose.yml").write_text(compose, encoding="utf-8")
        # Required-service audit is for the real repo. Call the lower-level checker here.
        errors: list[str] = []
        builds = parse_builds(compose)
        assert [b["service"] for b in builds] == ["svc", "nb", "ui", "remote"], builds
        assert builds[1]["additional_contexts"]["netbox_config"] == "./cfg"
        env = {"IE_UI_DOCKERFILE": ""}
        # missing.py must fail; app.py and stage copy must not; dockerignored skip.md must fail if copied.
        (root / "svc" / "Dockerfile").write_text(
            "FROM alpine AS build\n"
            "COPY app.py /app/app.py\n"
            "COPY README.md /README.md\n"
            "COPY skip.md /skip.md\n"
            "COPY secret.txt /secret.txt\n"
            "COPY --from=build /out/app /out/app\n"
            "COPY [\"app.py\", \"/app/also.py\"]\n",
            encoding="utf-8",
        )
        errors, _notes = _check_parsed(root, builds, env)
        joined = "\n".join(errors)
        assert "missing.py" not in joined
        assert "skip.md" in joined, joined
        assert "secret.txt" in joined, joined
        assert "README.md" not in joined, joined
        assert "app.py" not in joined, joined
        assert "--from=build" not in joined, joined
        # netbox-style named context
        nb_errors = [e for e in errors if e.startswith("FAIL nb")]
        assert nb_errors == [], nb_errors
        ui_errors = [e for e in errors if "ui/" in e or e.startswith("FAIL ui")]
        assert ui_errors == [], ui_errors
        # A COPY of a file that is not in the named context fails.
        (root / "nb" / "Dockerfile").write_text(
            "FROM alpine\nCOPY --from=netbox_config absent.py /etc/absent.py\n",
            encoding="utf-8",
        )
        errors, _notes = _check_parsed(root, builds, env)
        assert any("absent.py" in e and "netbox_config" in e for e in errors), errors
        # Unknown --from is an error, not a silent skip.
        (root / "nb" / "Dockerfile").write_text(
            "FROM alpine\nCOPY --from=not_a_stage plugins.py /etc/plugins.py\n",
            encoding="utf-8",
        )
        errors, _notes = _check_parsed(root, builds, env)
        assert any("not_a_stage" in e for e in errors), errors


def _check_parsed(root: Path, builds: list[dict], env: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    for build in builds:
        service = build["service"]
        context_value = resolve_vars(build["context"], env)
        if is_remote(context_value):
            notes.append(f"skip {service}: remote build context")
            continue
        context = project_path(root, context_value)
        dockerfile_value = resolve_vars(build.get("dockerfile") or "Dockerfile", env) or "Dockerfile"
        selected = context / dockerfile_value
        additional = {
            name: project_path(root, resolve_vars(path, env))
            for name, path in build["additional_contexts"].items()
        }
        for dockerfile in dockerfile_names(selected):
            check_dockerfile(service, dockerfile, context, additional, errors)
    return errors, notes


def main() -> int:
    try:
        self_test()
    except Exception as exc:  # noqa: BLE001 — self-test should fail the audit, not hide the cause
        print(f"FAIL self-test: {exc}", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    errors, notes = check_root(root)
    for note in notes:
        print(note)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"ok: {len(notes)} build dockerfile(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
