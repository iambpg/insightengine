#!/usr/bin/env python3
"""End-to-end test of setup/server.py against a stub docker CLI and stub scripts in a
temporary project dir. It proves the API/state machine/validation logic ONLY - no real
Docker daemon, no real migration. Run: python3 setup/tests/test_setup_api.py"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class _AdminStub(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        # The stub records that a password arrived and never writes it out.
        try:
            body = json.loads(raw.decode())
        except ValueError:
            body = {}
        if not body.get("email") or not body.get("password"):
            self.send_response(400); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, fmt, *args):
        return


def _start_admin_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 18250), _AdminStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


_start_admin_stub()

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "server.py")
STATIC = os.path.join(os.path.dirname(HERE), "static")
TOKEN = "test-token-not-a-real-secret"
PORT = 18099
BASE = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, token=TOKEN, edge=False, raw=False):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if edge:
        req.add_header("X-Setup-Edge", "1")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(req, data, timeout=10)
        code, txt, hdr = r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        code, txt, hdr = e.code, e.read().decode(), e.headers
    if raw:
        return code, txt, hdr
    try:
        return code, json.loads(txt) if txt else {}
    except ValueError:
        return code, txt


def rd(path):
    with open(path) as f:
        return f.read()


def wait_job(timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        c, s = call("GET", "/setup/state")
        if s.get("job") and s["job"]["state"] != "running" and s["state"] != "applying":
            return s
        time.sleep(0.2)
    raise AssertionError("job did not finish")


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="ie-setup-test-")
        os.makedirs(os.path.join(cls.root, "scripts"))
        os.makedirs(os.path.join(cls.root, "migration"))
        os.makedirs(os.path.join(cls.root, "data", "migration"))
        with open(os.path.join(cls.root, ".env"), "w") as f:
            f.write("PUBLIC_HOST='h'\nCLIENT_NAME='unconfigured'\nCLIENT_SLUG='unconfigured'\nSECRET_STAYS='keep-me'\n")
        os.chmod(os.path.join(cls.root, ".env"), 0o600)
        with open(os.path.join(cls.root, "docker-compose.yml"), "w") as f:
            f.write("services: {}\n")
        pre = os.path.join(cls.root, "scripts", "migrate.sh")
        with open(pre, "w") as f:
            f.write('#!/usr/bin/env bash\ncase "$1" in\n preflight) echo ok; printf \'{"time":"t","errors":%s,"warnings":0,"log":"x"}\' "${STUB_PF_ERRORS:-0}" > "$(dirname "$0")/../data/migration/preflight.json"; [ "${STUB_PF_ERRORS:-0}" = 0 ];;\n run) echo \'{"step":"copy","state":"done"}\' >> "$(dirname "$0")/../data/migration/progress.json"; echo run-ok;;\n esac\n')
        os.chmod(pre, 0o755)
        ph = os.path.join(cls.root, "scripts", "prom-history.sh")
        with open(ph, "w") as f:
            f.write('#!/usr/bin/env bash\necho "history $*"\n')
        os.chmod(ph, 0o755)
        cls.tokfile = os.path.join(cls.root, "token")
        with open(cls.tokfile, "w") as f:
            f.write(TOKEN)
        cls.oldroot = tempfile.mkdtemp(prefix="ie-old-")
        env = dict(os.environ, INSTALL_DIR=cls.root, SETUP_TOKEN_FILE=cls.tokfile, SETUP_PORT=str(PORT),
                   SETUP_BIND="127.0.0.1", SETUP_OLD_STACK_ROOT=cls.oldroot, SETUP_STATIC_DIR=STATIC,
                   PATH=os.path.join(HERE, "stubbin") + os.pathsep + os.environ["PATH"],
                   STUB_DOCKER_LOG=os.path.join(cls.root, "docker.calls"),
                   IE_CONFIG_URL="http://127.0.0.1:18250")
        cls.p = subprocess.Popen([sys.executable, SERVER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                call("GET", "/setup/healthz"); break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.p.terminate(); cls.p.wait()
        shutil.rmtree(cls.root, ignore_errors=True); shutil.rmtree(cls.oldroot, ignore_errors=True)

    def old(self, p):
        return os.path.join(self.oldroot, p)

    def test_01_initial_and_auth(self):
        c, s = call("GET", "/setup/state", token=None)
        self.assertEqual((c, s), (200, {"state": "unconfigured", "step": "client"}))
        self.assertEqual(call("GET", "/setup/state", token="wrong")[0], 401)
        self.assertEqual(call("POST", "/setup/client", {"client_name": "x"}, token=None)[0], 401)
        self.assertEqual(call("GET", "/setup/log", token=None)[0], 401)
        code, txt, h = call("GET", "/setup/gate", raw=True)
        self.assertEqual(code, 302); self.assertEqual(h["Location"], "/setup/")
        code, txt, h = call("GET", "/setup/", raw=True)
        self.assertEqual(code, 200); self.assertIn("first-run setup", txt)
        self.assertNotIn(TOKEN, txt)

    def test_02_validation(self):
        for bad in ("", "  ", "a'b", "a$b", "x" * 61, "!!!", "unconfigured"):
            self.assertEqual(call("POST", "/setup/client", {"client_name": bad})[0], 400, bad)
        self.assertEqual(call("POST", "/setup/mode", {"mode": "new"})[0], 409)   # client first

    def test_03_new_install_flow(self):
        env_path = os.path.join(self.root, ".env")
        before = os.stat(env_path)
        c, s = call("POST", "/setup/client", {"client_name": "Acme Corp"})
        self.assertEqual((c, s["client_slug"]), (202, "acme-corp"))
        s = wait_job()
        self.assertEqual((s["state"], s["step"]), ("unconfigured", "admin"))
        self.assertEqual(call("POST", "/setup/mode", {"mode": "new"})[0], 409)
        c, s = call("POST", "/setup/admin", {"email": "admin@example.com", "password": "correct-horse-1"})
        self.assertEqual((c, s["step"]), (200, "mode"))
        self.assertNotIn("correct-horse-1", rd(os.path.join(self.root, "data", "setup", "setup.log")))
        env = rd(env_path)
        self.assertIn("CLIENT_NAME='Acme Corp'", env); self.assertIn("CLIENT_SLUG='acme-corp'", env)
        self.assertIn("SECRET_STAYS='keep-me'", env)
        after = os.stat(env_path)
        self.assertEqual(after.st_mode & 0o777, 0o600)
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
        calls = rd(os.path.join(self.root, "docker.calls"))
        self.assertIn("up -d --no-build caddy netbox prometheus", calls)
        self.assertNotIn("docker-socket-proxy", calls.split("up -d")[1])
        self.assertNotIn(" setup", calls.split("up -d")[1])
        okb = {"netbox_pg_container": "c", "netbox_db_password_file": self.old("pw")}
        self.assertEqual(call("POST", "/setup/migrate/preflight", {"old_stack": okb})[0], 409)  # not in move mode
        c, s = call("POST", "/setup/mode", {"mode": "new"})
        self.assertEqual((c, s["state"]), (200, "complete"))
        self.assertEqual(call("GET", "/setup/gate", raw=True)[0], 200)
        # persistent store
        cfg = json.loads(rd(os.path.join(self.root, "data", "setup", "config.json")))
        self.assertEqual((cfg["client_name"], cfg["state"]), ("Acme Corp", "complete"))

    def test_04_edge_lockdown_after_complete(self):
        self.assertEqual(call("GET", "/setup/state", token=None, edge=True)[0], 200)
        self.assertEqual(call("GET", "/setup/gate", edge=True, raw=True)[0], 200)
        self.assertEqual(call("GET", "/setup/log", edge=True)[0], 404)
        self.assertEqual(call("GET", "/setup/", edge=True, raw=True)[0], 404)
        self.assertEqual(call("GET", "/setup/log")[0], 200)     # internal caller (e.g. UI backend) still works

    def test_05_rename_requires_confirmation(self):
        c, s = call("POST", "/setup/client", {"client_name": "Beta Ltd"})
        self.assertEqual(c, 409)
        c, s = call("POST", "/setup/client", {"client_name": "Beta Ltd", "confirm_downtime": True})
        self.assertEqual(c, 202)
        s = wait_job()
        self.assertEqual((s["state"], s["client_slug"]), ("complete", "beta-ltd"))

    def test_06_settings_migration_validation_and_flow(self):
        good = {"netbox_pg_container": "old-netbox-db", "netbox_db_password_file": self.old("pw/nb.txt")}
        bads = [
            {},                                                        # required missing
            dict(good, netbox_db_password_file="relative/pw"),
            dict(good, netbox_db_password_file="/etc/passwd"),          # outside old-stack root
            dict(good, netbox_media_path=self.oldroot + "/../etc"),
            dict(good, netbox_pg_container="a;rm -rf /"),
            dict(good, netbox_db_password_file=os.path.join(self.root, "secrets/x")),   # inside project
            dict(good, surprise="1"),
        ]
        for b in bads:
            self.assertEqual(call("POST", "/setup/migrate/preflight", {"old_stack": b})[0], 400, b)
        os.environ["STUB_PF_ERRORS"] = "0"
        c, s = call("POST", "/setup/migrate/preflight", {"old_stack": dict(good, keep_dumps=True)})
        self.assertEqual(c, 202); pid = s["preflight_id"]
        conf = rd(os.path.join(self.root, "migration", "migrate.conf"))
        self.assertIn("OLD_NETBOX_PG_CONTAINER=old-netbox-db", conf)
        self.assertEqual(os.stat(os.path.join(self.root, "migration", "migrate.conf")).st_mode & 0o777, 0o600)
        s = wait_job()
        self.assertTrue(s["last_preflight"]["passed"])
        # run guards
        self.assertEqual(call("POST", "/setup/migrate/run", {"preflight_id": pid})[0], 400)           # no confirm
        self.assertEqual(call("POST", "/setup/migrate/run", {"preflight_id": "nope", "confirm": True})[0], 409)
        c, s = call("POST", "/setup/migrate/run", {"preflight_id": pid, "confirm": True})
        self.assertEqual(c, 202); wait_job()
        c, st = call("GET", "/setup/migrate/status")
        self.assertEqual(st["job"]["state"], "succeeded")
        self.assertTrue(any(p.get("step") == "copy" for p in st["progress"]))
        self.assertEqual(call("GET", "/setup/state")[1]["state"], "complete")   # state unchanged in Settings

    def test_07_history_validation(self):
        for b in ({"mode": "x"}, {"mode": "keep", "method": "dir"}, {"mode": "keep", "method": "dir", "old_data_dir": "/etc"},
                  {"mode": "keep", "method": "snapshot", "old_data_dir": self.old("p"), "old_url": "file:///etc/passwd"},
                  {"mode": "keep", "method": "snapshot", "old_data_dir": self.old("p"), "old_url": "http://x;y"}):
            self.assertEqual(call("POST", "/setup/prom-history", b)[0], 400, b)
        c, s = call("POST", "/setup/prom-history", {"mode": "keep", "method": "snapshot", "old_url": "http://host.docker.internal:9090", "old_data_dir": self.old("prom")})
        self.assertEqual(c, 202); wait_job()
        log = call("GET", "/setup/log?lines=50")[1]["lines"]
        self.assertTrue(any("history import --from-snapshot http://host.docker.internal:9090" in l for l in log))
        self.assertFalse(any(TOKEN in l for l in log))

    def test_08_no_token_leak_and_unknown_route(self):
        self.assertEqual(call("GET", "/setup/nope")[0], 404)
        full = call("GET", "/setup/state")[1]
        self.assertNotIn(TOKEN, json.dumps(full))


class TMove(unittest.TestCase):
    """Fresh instance: first-run MOVE flow."""
    @classmethod
    def setUpClass(cls):
        global PORT, BASE
        PORT, BASE = 18100, "http://127.0.0.1:18100"
        T.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        T.tearDownClass.__func__(cls)

    old = T.old

    def test_10_move_first_run(self):
        os.environ.pop("STUB_PF_ERRORS", None)
        self.assertEqual(call("POST", "/setup/client", {"client_name": "Gamma"})[0], 202)
        s = wait_job(); self.assertEqual(s["step"], "admin")
        c, s = call("POST", "/setup/admin", {"email": "ops@example.com", "generate": True})
        self.assertEqual((c, s["step"]), (200, "mode"))
        pw = s.get("generated_password")
        self.assertTrue(isinstance(pw, str) and len(pw) >= 12)
        self.assertNotIn(pw, rd(os.path.join(self.root, "data", "setup", "setup.log")))
        self.assertEqual(call("POST", "/setup/mode", {"mode": "move"})[1]["step"], "migrate")
        # history not yet allowed
        self.assertEqual(call("POST", "/setup/prom-history", {"mode": "fresh"})[0], 409)
        good = {"netbox_pg_container": "old-db", "netbox_db_password_file": self.old("pw")}
        c, s = call("POST", "/setup/migrate/preflight", {"old_stack": good}); self.assertEqual(c, 202)
        s = wait_job(); self.assertTrue(s["last_preflight"]["passed"])
        c, r = call("POST", "/setup/migrate/run", {"preflight_id": s["last_preflight"]["id"], "confirm": True}); self.assertEqual(c, 202)
        s = wait_job(); self.assertEqual((s["state"], s["step"]), ("unconfigured", "history"))
        self.assertEqual(call("GET", "/setup/gate", raw=True)[0], 302)
        c, r = call("POST", "/setup/prom-history", {"mode": "fresh"})
        self.assertEqual((c, r["state"]), (200, "complete"))
        self.assertEqual(call("GET", "/setup/gate", raw=True)[0], 200)


class TFail(unittest.TestCase):
    """A failing `compose up` -> state=failed, gate stays closed, retry possible."""
    @classmethod
    def setUpClass(cls):
        global PORT, BASE
        PORT, BASE = 18101, "http://127.0.0.1:18101"
        os.environ["STUB_UP_FAIL"] = "1"
        T.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("STUB_UP_FAIL", None)
        T.tearDownClass.__func__(cls)

    def test_20_failed_apply(self):
        self.assertEqual(call("POST", "/setup/client", {"client_name": "Delta"})[0], 202)
        t = time.time()
        while time.time() - t < 15:
            s = call("GET", "/setup/state")[1]
            if s["state"] != "applying":
                break
            time.sleep(0.2)
        self.assertEqual(s["state"], "failed"); self.assertIn("up failed", s["error"])
        self.assertEqual(call("GET", "/setup/gate", raw=True)[0], 302)
        self.assertEqual(call("POST", "/setup/mode", {"mode": "new"})[0], 409)
        self.assertEqual(call("POST", "/setup/client", {"client_name": "Delta"})[0], 202)   # retry allowed


if __name__ == "__main__":
    unittest.main(verbosity=2)
