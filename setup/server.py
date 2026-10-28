#!/usr/bin/env python3
"""InsightEngine setup service (first run + Settings).

* Python standard library only.  Listens on :8099 inside the container, no published port.
* Token-authenticated (Bearer).  The token is read from a secret file and never logged,
  never returned, never put in the page.
* A FIXED set of actions - there is no endpoint that runs an arbitrary command:
    render  : write CLIENT_NAME / CLIENT_SLUG into .env from the config store
    apply   : `docker compose up -d` for THIS project (all services except itself and the proxy)
    migrate : scripts/migrate.sh preflight | run | status
    history : scripts/prom-history.sh import ...
* Persistent single config store: <INSTALL_DIR>/data/setup/config.json
* State machine: unconfigured -> applying -> (unconfigured/step=admin -> mode ...) -> complete | failed
See docs/setup-api.md.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.abspath(os.environ.get("INSTALL_DIR", "/opt/insightengine"))
DATA = os.path.join(ROOT, "data", "setup")
CONFIG_FILE = os.path.join(DATA, "config.json")
JOB_FILE = os.path.join(DATA, "job.json")
LOG_FILE = os.path.join(DATA, "setup.log")
MIGRATE_CONF = os.path.join(ROOT, "migration", "migrate.conf")
MIGRATE_DIR = os.path.join(ROOT, "data", "migration")
TOKEN_FILE = os.environ.get("SETUP_TOKEN_FILE", "/run/secrets/setup_token")
OLD_ROOT = os.path.abspath(os.environ.get("SETUP_OLD_STACK_ROOT", "/opt"))
PUBLIC_AFTER_COMPLETE = os.environ.get("SETUP_PUBLIC_AFTER_COMPLETE", "no").lower() in ("1", "yes", "true")
STATIC_DIR = os.environ.get("SETUP_STATIC_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
BIND = os.environ.get("SETUP_BIND", "0.0.0.0")
PORT = int(os.environ.get("SETUP_PORT", "8099"))
KEEP_SERVICES = {"setup", "docker-socket-proxy"}   # never recreated by apply (they run this code)
MAX_BODY = 64 * 1024
RESERVED_SLUG = "unconfigured"

LOCK = threading.RLock()
CONFIG = {}
JOB = {}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ----------------------------------------------------------------- persistence
def _atomic_write(path, text, mode=0o600):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    st = os.stat(path) if os.path.exists(path) else None
    if st is not None:
        mode = st.st_mode & 0o777
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    if st is not None:
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
    os.replace(tmp, path)


def default_config():
    return {"schema": 1, "state": "unconfigured", "step": "client",
            "client_name": RESERVED_SLUG, "client_slug": RESERVED_SLUG,
            "mode": None, "history": None, "migrated": False, "last_preflight": None,
            "error": None, "updated_at": now()}


def save_config():
    CONFIG["updated_at"] = now()
    _atomic_write(CONFIG_FILE, json.dumps(CONFIG, indent=2))


def save_job():
    _atomic_write(JOB_FILE, json.dumps(JOB, indent=2))


def log(line):
    with open(LOG_FILE, "a") as f:
        f.write("%s %s\n" % (now(), line.rstrip("\n")))


def load_all():
    global CONFIG, JOB
    os.makedirs(DATA, exist_ok=True)
    try:
        with open(CONFIG_FILE) as f:
            CONFIG = json.load(f)
    except (OSError, ValueError):
        CONFIG = default_config()
        save_config()
    try:
        with open(JOB_FILE) as f:
            JOB = json.load(f)
    except (OSError, ValueError):
        JOB = {}
    # A restart while something was running = interrupted.
    if JOB.get("state") == "running":
        JOB.update(state="failed", finished=now(), error="interrupted by service restart")
        save_job()
    if CONFIG.get("state") == "applying":
        CONFIG.update(state="failed", error="apply interrupted by service restart")
        save_config()


# ------------------------------------------------------------------ validation
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s


def valid_client_name(name):
    if not isinstance(name, str):
        return None, "client_name must be a string"
    name = name.strip()
    if not 1 <= len(name) <= 60:
        return None, "client_name must be 1-60 characters"
    if re.search(r"[\x00-\x1f\x7f'\"`$\\]", name):
        return None, "client_name must not contain quotes, $, backslash or control characters"
    slug = slugify(name)
    if not slug:
        return None, "client_name needs at least one letter or digit"
    if slug == RESERVED_SLUG:
        return None, "that name is reserved; choose the real client name"
    return (name, slug), None


RE_CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RE_DBNAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
RE_PATH = re.compile(r"^/[A-Za-z0-9_.@+/-]{0,400}$")
RE_URL = re.compile(r"^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?(/[A-Za-z0-9._/-]*)?$")


def safe_old_path(p):
    """Absolute, no '..', inside the read-only old-stack mount, not inside this project."""
    if not isinstance(p, str) or not RE_PATH.match(p) or ".." in p.split("/"):
        return False
    p = os.path.normpath(p)
    inside = lambda base: p == base or p.startswith(base.rstrip("/") + "/")
    return inside(OLD_ROOT) and not inside(ROOT)


MIGRATE_FIELDS = [
    # (api key, conf key, kind, required)
    ("compose_file", "OLD_COMPOSE_FILE", "path", False),
    ("stack_dir", "OLD_STACK_DIR", "path", False),
    ("netbox_container", "OLD_NETBOX_CONTAINER", "container", False),
    ("netbox_pg_container", "OLD_NETBOX_PG_CONTAINER", "container", True),
    ("netbox_db", "OLD_NETBOX_DB", "db", False),
    ("netbox_db_user", "OLD_NETBOX_DB_USER", "db", False),
    ("netbox_db_password_file", "OLD_NETBOX_DB_PASSWORD_FILE", "path", True),
    ("netdisco_pg_container", "OLD_NETDISCO_PG_CONTAINER", "container", False),
    ("netdisco_db", "OLD_NETDISCO_DB", "db", False),
    ("netdisco_db_user", "OLD_NETDISCO_DB_USER", "db", False),
    ("netdisco_db_password_file", "OLD_NETDISCO_DB_PASSWORD_FILE", "path", False),
    ("netbox_media_path", "OLD_NETBOX_MEDIA_PATH", "path", False),
    ("grafana_data_path", "OLD_GRAFANA_DATA_PATH", "path", False),
    ("grafana_provisioning_path", "OLD_GRAFANA_PROVISIONING_PATH", "path", False),
    ("grafana_container", "OLD_GRAFANA_CONTAINER", "container", False),
    ("alertmanager_config_path", "OLD_ALERTMANAGER_CONFIG_PATH", "path", False),
    ("caddyfile_path", "OLD_CADDYFILE_PATH", "path", False),
    ("prom_container", "OLD_PROM_CONTAINER", "container", False),
]


def build_migrate_conf(body):
    """Validate the 'old_stack' object and return the migrate.conf text. Passwords are
    only ever FILE PATHS (read by migrate.sh, handed to the old DB container over stdin)."""
    if not isinstance(body, dict):
        return None, "old_stack must be an object"
    known = {f[0] for f in MIGRATE_FIELDS} | {"keep_dumps"}
    extra = sorted(set(body) - known)
    if extra:
        return None, "unknown field(s): " + ", ".join(extra)
    lines = ["# written by the setup service - paths only, no secrets"]
    for api, conf, kind, required in MIGRATE_FIELDS:
        v = body.get(api)
        if v in (None, ""):
            if required:
                return None, "%s is required" % api
            continue
        if not isinstance(v, str):
            return None, "%s must be a string" % api
        ok = {"path": safe_old_path, "container": lambda x: bool(RE_CONTAINER.match(x)),
              "db": lambda x: bool(RE_DBNAME.match(x))}[kind](v)
        if not ok:
            hint = {"path": "an absolute path under %s (read-only mount), outside %s" % (OLD_ROOT, ROOT),
                    "container": "a container name", "db": "a database/user name"}[kind]
            return None, "%s must be %s" % (api, hint)
        lines.append("%s=%s" % (conf, v))
    kd = body.get("keep_dumps", True)
    lines.append("KEEP_DUMPS=%s" % ("yes" if kd in (True, "yes", "true", 1) else "no"))
    return "\n".join(lines) + "\n", None


# ------------------------------------------------------------------------ jobs
def compose(*args):
    return ["docker", "compose", "--project-directory", ROOT] + list(args)


def run_cmd(args, capture=None, timeout=3600, env_extra=None):
    """Run a fixed argv (never a shell string), stream output to the setup log."""
    log("$ " + " ".join(shlex.quote(a) for a in args))
    env = dict(os.environ)
    env.update(env_extra or {})
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         stdin=subprocess.DEVNULL, cwd=ROOT, env=env)
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        for line in p.stdout:
            line = line.rstrip("\n")
            log("  " + line)
            if capture is not None:
                capture.append(line)
        rc = p.wait()
    finally:
        timer.cancel()
    log("  exit %d" % rc)
    return rc


def start_job(kind, fn, on_done=None):
    """Start a background job. Caller must hold LOCK and have checked no job is running."""
    jid = uuid.uuid4().hex[:12]
    JOB.clear()
    JOB.update(id=jid, kind=kind, state="running", started=now(), finished=None, exit_code=None, error=None)
    save_job()

    def runner():
        err, rc = None, 0
        try:
            rc, err = fn()
        except Exception as e:  # keep the service alive whatever happens
            rc, err = 1, "internal error: %s" % e.__class__.__name__
            log("internal error: %r" % e)
        with LOCK:
            JOB.update(state="succeeded" if rc == 0 else "failed", finished=now(), exit_code=rc, error=err)
            save_job()
            if on_done:
                on_done(rc == 0, err)
    threading.Thread(target=runner, daemon=True).start()
    return jid


def job_running():
    return JOB.get("state") == "running"


# --- render + apply (client name) ---
def update_env_key(text, key, value):
    out, done = [], False
    for ln in text.splitlines():
        if ln.startswith(key + "="):
            out.append("%s='%s'" % (key, value))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s='%s'" % (key, value))
    return "\n".join(out) + "\n"


def render_env():
    """The only 'template' step: CLIENT_NAME/CLIENT_SLUG -> .env (all other config reads these)."""
    path = os.path.join(ROOT, ".env")
    with open(path) as f:
        text = f.read()
    text = update_env_key(text, "CLIENT_NAME", CONFIG["client_name"])
    text = update_env_key(text, "CLIENT_SLUG", CONFIG["client_slug"])
    mode = os.stat(path).st_mode & 0o777
    _atomic_write(path, text, mode)


def do_apply():
    log("render: .env <- client '%s' (%s)" % (CONFIG["client_name"], CONFIG["client_slug"]))
    try:
        render_env()
    except OSError as e:
        return 1, "render failed: %s" % e.strerror
    out = []
    if run_cmd(compose("config", "--services"), capture=out, timeout=120) != 0:
        return 1, "docker compose config failed (see log)"
    services = sorted(s.strip() for s in out if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", s.strip()))
    services = [s for s in services if s not in KEEP_SERVICES]
    if not services:
        return 1, "no services found"
    rc = run_cmd(compose("up", "-d", "--no-build", *services), timeout=1800)
    return (0, None) if rc == 0 else (rc, "docker compose up failed (see log)")


def apply_done_factory(was_complete, prev_step):
    def done(ok, err):
        if ok:
            CONFIG["error"] = None
            if was_complete:
                CONFIG.update(state="complete", step="done")
            else:
                CONFIG.update(state="unconfigured", step="admin" if prev_step == "client" else prev_step)
        else:
            CONFIG.update(state="failed", error=err)
        save_config()
    return done


# --- migration ---
def sha256_file(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def read_json_file(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def do_preflight():
    def fn():
        jid = JOB.get("id")
        rc = run_cmd([os.path.join(ROOT, "scripts", "migrate.sh"), "preflight"], env_extra={"MIGRATE_CONF": MIGRATE_CONF}, timeout=1800)
        pf = read_json_file(os.path.join(MIGRATE_DIR, "preflight.json")) or {}
        passed = rc == 0 and pf.get("errors", 1) == 0
        with LOCK:
            CONFIG["last_preflight"] = {"id": jid, "passed": passed, "errors": pf.get("errors"),
                                        "warnings": pf.get("warnings"), "time": now(),
                                        "conf_sha256": sha256_file(MIGRATE_CONF)}
            save_config()
        return (0, None) if passed else (1 if rc == 0 else rc, "preflight reported errors (see log)")
    return fn


def do_migrate_run():
    rc = run_cmd([os.path.join(ROOT, "scripts", "migrate.sh"), "run"], env_extra={"MIGRATE_CONF": MIGRATE_CONF}, timeout=6 * 3600)
    return (0, None) if rc == 0 else (rc, "migration failed (see log); the old stack was not touched")


def migrate_run_done(ok, err):
    if ok:
        CONFIG["migrated"] = True
        if CONFIG["state"] == "unconfigured" and CONFIG["step"] == "migrate":
            CONFIG["step"] = "history"
        CONFIG["error"] = None
        save_config()


def do_history(args):
    def fn():
        rc = run_cmd([os.path.join(ROOT, "scripts", "prom-history.sh")] + args, timeout=6 * 3600)
        return (0, None) if rc == 0 else (rc, "prometheus history import failed (see log)")
    return fn


def finish_setup():
    CONFIG.update(state="complete", step="done", error=None)
    save_config()
    # Seed runs only in the compose service (SETUP_RUN_SEED=yes). Tests leave it unset.
    # The script reads the NetBox token from a file and does not print it.
    if os.environ.get("SETUP_RUN_SEED", "").lower() in ("1", "yes", "true", "on"):
        script = os.path.join(ROOT, "scripts", "seed-netbox.sh")

        def run():
            run_cmd([script], env_extra={"NETBOX_INTERNAL_URL": os.environ.get("NETBOX_INTERNAL_URL", "http://netbox:8080")}, timeout=600)

        threading.Thread(target=run, name="seed-netbox", daemon=True).start()


def _password_ok(password):
    if not isinstance(password, str) or not (12 <= len(password) <= 200):
        return False
    if any(ord(c) < 32 for c in password):
        return False
    return any(c.isalpha() for c in password) and any(c.isdigit() for c in password)


def _email_ok(email):
    if not isinstance(email, str):
        return False
    email = email.strip()
    if not (3 <= len(email) <= 320) or email.count("@") != 1 or any(c.isspace() for c in email):
        return False
    local, _, domain = email.partition("@")
    return bool(local) and "." in domain


def _generate_password():
    password = secrets.token_urlsafe(18)
    if not any(c.isdigit() for c in password):
        password += "1"
    if not any(c.isalpha() for c in password):
        password += "a"
    return password


def bootstrap_admin(email, password):
    """Ask ie-config to create the first Administrator. The password is not logged."""
    base = os.environ.get("IE_CONFIG_URL", "http://ie-config:8080").rstrip("/")
    data = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(base + "/internal/bootstrap-admin", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + get_token())
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except OSError:
        return 0, b""


# ------------------------------------------------------------------- responses
class Err(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def public_state():
    return {"state": CONFIG["state"], "step": CONFIG["step"]}


def full_state():
    s = public_state()
    s.update(client_name=CONFIG["client_name"], client_slug=CONFIG["client_slug"],
             mode=CONFIG["mode"], history=CONFIG["history"], migrated=CONFIG["migrated"],
             error=CONFIG["error"], updated_at=CONFIG["updated_at"],
             job=({k: JOB.get(k) for k in ("id", "kind", "state", "started", "finished", "exit_code", "error")} if JOB else None),
             last_preflight=CONFIG["last_preflight"])
    return s


def progress_lines(n=100):
    out = []
    try:
        with open(os.path.join(MIGRATE_DIR, "progress.json")) as f:
            for ln in f.readlines()[-n:]:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 262144))
            data = f.read().decode("utf-8", "replace")
        return data.splitlines()[-n:], size
    except OSError:
        return [], 0


# --------------------------------------------------------------------- handler
FAILS = {}   # client key -> [timestamps]
TOKEN = {"v": None}


def get_token():
    if TOKEN["v"] is None:
        try:
            with open(TOKEN_FILE) as f:
                TOKEN["v"] = f.read().strip()
        except OSError:
            TOKEN["v"] = ""
    return TOKEN["v"]


class Handler(BaseHTTPRequestHandler):
    server_version = "setup"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # never log paths with query/tokens
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args if args else fmt))

    # ---- helpers
    def send_json(self, code, obj, extra=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def client_key(self):
        if self.headers.get("X-Setup-Edge"):
            return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        return self.client_address[0]

    def authed(self):
        key = self.client_key()
        t = time.time()
        recent = [x for x in FAILS.get(key, []) if t - x < 60]
        FAILS[key] = recent
        if len(recent) >= 10:
            raise Err(429, "too many failed attempts; wait a minute")
        tok = get_token()
        h = self.headers.get("Authorization", "")
        ok = bool(tok) and h.startswith("Bearer ") and hmac.compare_digest(h[7:].encode(), tok.encode())
        if not ok:
            FAILS[key].append(t)
            raise Err(401, "missing or invalid token")

    def edge_blocked(self, path):
        return (self.headers.get("X-Setup-Edge") and CONFIG.get("state") == "complete"
                and not PUBLIC_AFTER_COMPLETE and path not in ("/setup/state", "/setup/gate", "/setup/healthz"))

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise Err(413, "body too large")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
        except ValueError:
            raise Err(400, "body must be JSON")
        if not isinstance(obj, dict):
            raise Err(400, "body must be a JSON object")
        return obj

    def static(self, name, ctype):
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                body = f.read()
        except OSError:
            raise Err(404, "not found")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # ---- dispatch
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if path == "/setup":
            path = "/setup/"
        q = parse_qs(u.query)
        try:
            with LOCK:
                blocked = self.edge_blocked(path)
            if blocked:
                raise Err(404, "not found")
            if method == "GET" and path in ("/setup/", "/setup/index.html"):
                return self.static("index.html", "text/html; charset=utf-8")
            if method == "GET" and path == "/setup/app.js":
                return self.static("app.js", "application/javascript; charset=utf-8")
            if method == "GET" and path == "/setup/style.css":
                return self.static("style.css", "text/css; charset=utf-8")
            if method == "GET" and path == "/setup/healthz":
                return self.send_json(200, {"ok": True})
            if method == "GET" and path == "/setup/gate":
                with LOCK:
                    ok = CONFIG["state"] == "complete"
                if ok:
                    return self.send_json(200, {"state": "complete"})
                self.send_response(302)
                self.send_header("Location", "/setup/")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if method == "GET" and path == "/setup/state":
                has_auth = bool(self.headers.get("Authorization"))
                if has_auth:
                    self.authed()
                with LOCK:
                    return self.send_json(200, full_state() if has_auth else public_state())
            routes = {
                ("POST", "/setup/client"): self.h_client,
                ("POST", "/setup/admin"): self.h_admin,
                ("POST", "/setup/mode"): self.h_mode,
                ("POST", "/setup/migrate/preflight"): self.h_preflight,
                ("POST", "/setup/migrate/run"): self.h_run,
                ("GET", "/setup/migrate/status"): self.h_status,
                ("POST", "/setup/prom-history"): self.h_history,
                ("GET", "/setup/log"): lambda: self.h_log(q),
            }
            h = routes.get((method, path))
            if h is None:
                raise Err(404, "not found")
            self.authed()
            body = self.read_body() if method == "POST" else None
            if method == "POST":
                self.h_body = body
            return h()
        except Err as e:
            return self.send_json(e.code, {"error": e.msg})
        except Exception as e:
            log("handler error: %r" % e)
            return self.send_json(500, {"error": "internal error"})

    # ---- handlers
    def h_client(self):
        b = self.h_body
        res, err = valid_client_name(b.get("client_name"))
        if err:
            raise Err(400, err)
        name, slug = res
        with LOCK:
            if job_running() or CONFIG["state"] == "applying":
                raise Err(409, "another action is running")
            was_complete = CONFIG["state"] == "complete"
            if was_complete and slug != CONFIG["client_slug"] and b.get("confirm_downtime") is not True:
                raise Err(409, "renaming recreates all containers (monitoring is down for several minutes); resend with confirm_downtime=true")
            prev_step = CONFIG["step"]
            CONFIG.update(client_name=name, client_slug=slug, state="applying", error=None)
            save_config()
            jid = start_job("apply", do_apply, apply_done_factory(was_complete, prev_step))
            self.send_json(202, {"state": "applying", "job_id": jid, "client_name": name, "client_slug": slug})

    def h_admin(self):
        body = self.h_body
        email = (body.get("email") or "").strip()
        if not _email_ok(email):
            raise Err(400, "email is not valid")
        generate = body.get("generate") is True
        if generate:
            password = _generate_password()
        else:
            password = body.get("password")
            if not _password_ok(password):
                raise Err(400, "password must be 12-200 characters and include a letter and a digit, or set generate=true")
        with LOCK:
            if CONFIG["state"] != "unconfigured" or CONFIG["step"] != "admin":
                raise Err(409, "the administrator is created after the client name (state=%s, step=%s)" % (CONFIG["state"], CONFIG["step"]))
        code, _raw = bootstrap_admin(email, password)
        # Do not log the password or the request body.
        log("bootstrap-admin email=%s result=%s" % (email, code))
        if code not in (200, 409):
            raise Err(502, "could not create the administrator (ie-config returned %s)" % code)
        with LOCK:
            CONFIG["step"] = "mode"
            save_config()
            out = public_state()
            if generate and code == 200:
                out["generated_password"] = password
            self.send_json(200, out)

    def h_mode(self):
        mode = self.h_body.get("mode")
        if mode not in ("new", "move"):
            raise Err(400, "mode must be 'new' or 'move'")
        with LOCK:
            if CONFIG["state"] == "complete":
                if mode == "move":
                    return self.send_json(200, {"state": "complete", "note": "already set up; use /setup/migrate/* directly"})
                raise Err(409, "already complete")
            if CONFIG["state"] != "unconfigured" or CONFIG["step"] != "mode":
                raise Err(409, "create the administrator first (state=%s, step=%s)" % (CONFIG["state"], CONFIG["step"]))
            if job_running():
                raise Err(409, "another action is running")
            CONFIG["mode"] = mode
            if mode == "new":
                finish_setup()
            else:
                CONFIG["step"] = "migrate"
                save_config()
            self.send_json(200, public_state())

    def migrate_allowed(self):
        if CONFIG["state"] == "complete":
            return
        if CONFIG["state"] == "unconfigured" and CONFIG["mode"] == "move" and CONFIG["step"] in ("migrate", "history"):
            return
        raise Err(409, "migration is not available in state=%s step=%s mode=%s" % (CONFIG["state"], CONFIG["step"], CONFIG["mode"]))

    def h_preflight(self):
        conf, err = build_migrate_conf(self.h_body.get("old_stack"))
        if err:
            raise Err(400, err)
        with LOCK:
            self.migrate_allowed()
            if job_running():
                raise Err(409, "another action is running")
            os.makedirs(os.path.dirname(MIGRATE_CONF), exist_ok=True)
            _atomic_write(MIGRATE_CONF, conf, 0o600)
            CONFIG["last_preflight"] = None
            save_config()
            jid = start_job("preflight", do_preflight())
            self.send_json(202, {"job_id": jid, "preflight_id": jid})

    def h_run(self):
        b = self.h_body
        with LOCK:
            self.migrate_allowed()
            if job_running():
                raise Err(409, "another action is running")
            pf = CONFIG.get("last_preflight")
            if b.get("confirm") is not True:
                raise Err(400, "confirm=true is required")
            if not pf or not pf.get("passed") or pf.get("id") != b.get("preflight_id"):
                raise Err(409, "run a passing preflight first and send its preflight_id")
            if pf.get("conf_sha256") != sha256_file(MIGRATE_CONF):
                raise Err(409, "settings changed since the preflight; run it again")
            jid = start_job("migrate", do_migrate_run, migrate_run_done)
            self.send_json(202, {"job_id": jid})

    def h_status(self):
        with LOCK:
            job = {k: JOB.get(k) for k in ("id", "kind", "state", "started", "finished", "exit_code", "error")} if JOB else None
            pf = CONFIG.get("last_preflight")
        lines, _ = tail(LOG_FILE, 40)
        pj = read_json_file(os.path.join(MIGRATE_DIR, "preflight.json"))
        self.send_json(200, {"job": job, "preflight": pf, "preflight_log": (pj or {}).get("log"),
                             "progress": progress_lines(100), "log_tail": lines})

    def h_history(self):
        b = self.h_body
        mode = b.get("mode")
        if mode not in ("keep", "fresh"):
            raise Err(400, "mode must be 'keep' or 'fresh'")
        args = None
        if mode == "keep":
            method, ddir = b.get("method"), b.get("old_data_dir")
            if not isinstance(ddir, str) or not safe_old_path(ddir):
                raise Err(400, "old_data_dir must be an absolute path under %s (read-only mount)" % OLD_ROOT)
            if method == "snapshot":
                url = b.get("old_url")
                if not isinstance(url, str) or not RE_URL.match(url):
                    raise Err(400, "old_url must be an http(s) URL of the OLD Prometheus")
                args = ["import", "--from-snapshot", url, ddir]
            elif method == "dir":
                args = ["import", "--from-dir", ddir]
            else:
                raise Err(400, "method must be 'snapshot' or 'dir'")
        with LOCK:
            in_flow = CONFIG["state"] == "unconfigured" and CONFIG["step"] == "history"
            if not (in_flow or CONFIG["state"] == "complete"):
                raise Err(409, "not available in state=%s step=%s" % (CONFIG["state"], CONFIG["step"]))
            if job_running():
                raise Err(409, "another action is running")
            if mode == "fresh":
                CONFIG["history"] = "fresh"
                if in_flow:
                    finish_setup()
                else:
                    save_config()
                return self.send_json(200, public_state())

            def done(ok, err):
                if ok:
                    CONFIG["history"] = "keep"
                    if in_flow:
                        CONFIG.update(state="complete", step="done", error=None)
                    save_config()
            jid = start_job("prom-history", do_history(args), done)
            self.send_json(202, {"job_id": jid})

    def h_log(self, q):
        try:
            n = max(1, min(1000, int((q.get("lines") or ["200"])[0])))
        except ValueError:
            n = 200
        lines, size = tail(LOG_FILE, n)
        self.send_json(200, {"lines": lines, "size": size})


def main():
    load_all()
    if not get_token():
        sys.stderr.write("FATAL: setup token file %s missing or empty\n" % TOKEN_FILE)
        sys.exit(1)
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    sys.stderr.write("setup service listening on %s:%d (root=%s)\n" % (BIND, PORT, ROOT))
    srv.serve_forever()


if __name__ == "__main__":
    main()
