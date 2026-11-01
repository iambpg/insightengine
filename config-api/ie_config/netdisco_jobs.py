"""Insert and read Netdisco ``admin`` jobs the way netdisco-web does.

``jq_insert`` (App::Netdisco::JobQueue::PostgreSQL) writes ``device``, ``action``,
``subaction``, ``status='queued'``, ``username`` and ``userip``. The backend
daemon polls that table. A queued row with ``started``/``backend`` set is the
one the worker has locked; ``done`` and ``error`` are terminal. ``info`` is how
Netdisco records a duplicate.

ie-config's docker proxy allows container restart and blocks EXEC, so this
module does not shell out to ``netdisco-do``. A second discover of the same
address is not inserted while one is still queued or running: two of those
raced on ``device_pkey`` and one of them failed.
"""

from __future__ import annotations

import os

_ACTIONS = {"discover", "macsuck", "arpnip"}
_PLACEHOLDER = "unset-placeholder"
_SECRET_ENV = ("SNMP_V2_COMMUNITY", "SNMP_V3_AUTH_PASSWORD", "SNMP_V3_PRIV_PASSWORD", "SNMP_V3_USER", "SNMP_V3_USERNAME")


def map_admin_status(status: str, started, backend: str | None) -> str:
    """Map one ``admin`` row onto queued, running, done or error."""
    raw = (status or "").strip().lower()
    if raw == "running":
        return "running"
    if raw == "queued" or raw == "":
        if started or (backend or "").strip():
            return "running"
        return "queued"
    if raw == "done":
        return "done"
    return "error"


def scrub_log(text: str) -> str:
    """Netdisco's log line, with credential values removed."""
    redacted = text or ""
    for name in _SECRET_ENV:
        secret = (os.environ.get(name) or "").strip()
        if secret and secret != _PLACEHOLDER and len(secret) >= 4:
            redacted = redacted.replace(secret, "***")
    kept = []
    for line in redacted.splitlines():
        low = line.lower()
        if any(token in low for token in ("community:", "auth_pass", "priv_pass", "password:")):
            continue
        kept.append(line)
    return "\n".join(kept)[:2000]


def _view(job_id: int, ip: str, action: str, status: str, log: str, started, backend: str) -> dict:
    return {
        "id": int(job_id),
        "ip": ip or "",
        "action": action or "",
        "status": map_admin_status(status, started, backend),
        "log": scrub_log(log or ""),
    }


class MemoryAdmin:
    """In-memory stand-in for the ``admin`` table. Tests use this; production uses NetdiscoAdmin."""

    def __init__(self):
        self.rows: list[dict] = []
        self.neighbours: dict[str, list[str]] = {}
        self._next = 1

    def enqueue(self, ip: str, action: str, username: str, userip: str | None = None) -> dict:
        if action not in _ACTIONS:
            raise ValueError("unsupported netdisco action")
        for row in self.rows:
            if row["ip"] == ip and row["action"] == action and row["raw_status"] == "queued" and row["finished"] is None:
                return {"id": row["id"], "created": False}
        row = {
            "id": self._next,
            "ip": ip,
            "action": action,
            "raw_status": "queued",
            "log": "",
            "started": None,
            "finished": None,
            "backend": "",
            "username": username,
            "userip": userip,
        }
        self._next += 1
        self.rows.append(row)
        return {"id": row["id"], "created": True}

    def fetch(self, job_id: int) -> dict | None:
        for row in self.rows:
            if row["id"] == int(job_id):
                return _view(row["id"], row["ip"], row["action"], row["raw_status"], row["log"], row["started"], row["backend"])
        return None

    def neighbour_ips(self, ip: str) -> list[str]:
        return list(self.neighbours.get(ip) or [])

    def release_skipped(self, ip: str, action: str) -> bool:
        """Test double. Production reads device_skip; this set is optional."""
        skipped = getattr(self, "skipped", {})
        if action not in (skipped.get(ip) or []):
            return False
        changed = False
        for row in self.rows:
            if row["ip"] == ip and row["action"] == action and row["raw_status"] == "queued" and row["finished"] is None:
                row["raw_status"] = "done"
                row["finished"] = "skipped"
                row["log"] = "Netdisco skipped %s for this device." % action
                changed = True
        return changed

    def set_state(self, job_id: int, raw_status: str, log: str = "", started=None, finished=None, backend: str | None = None) -> None:
        for row in self.rows:
            if row["id"] == int(job_id):
                row["raw_status"] = raw_status
                row["log"] = log
                row["started"] = started
                row["finished"] = finished
                if backend is not None:
                    row["backend"] = backend
                return
        raise KeyError(job_id)


class NetdiscoAdmin:
    """psycopg access to Netdisco's ``admin`` table."""

    def __init__(self, url: str):
        self.url = url

    def _connect(self):
        import psycopg
        return psycopg.connect(self.url, connect_timeout=5)

    def enqueue(self, ip: str, action: str, username: str, userip: str | None = None) -> dict:
        if action not in _ACTIONS:
            raise ValueError("unsupported netdisco action")
        user = (username or "insightengine")[:200]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (ip, action))
                cur.execute(
                    "SELECT job FROM admin "
                    "WHERE device = %s::inet AND action = %s AND status = 'queued' AND finished IS NULL "
                    "ORDER BY job LIMIT 1 FOR UPDATE",
                    (ip, action),
                )
                existing = cur.fetchone()
                if existing:
                    conn.commit()
                    return {"id": int(existing[0]), "created": False}
                if userip:
                    cur.execute(
                        "INSERT INTO admin (device, action, status, username, userip) "
                        "VALUES (%s::inet, %s, 'queued', %s, %s::inet) RETURNING job",
                        (ip, action, user, userip),
                    )
                else:
                    cur.execute(
                        "INSERT INTO admin (device, action, status, username) "
                        "VALUES (%s::inet, %s, 'queued', %s) RETURNING job",
                        (ip, action, user),
                    )
                job_id = int(cur.fetchone()[0])
            conn.commit()
        return {"id": job_id, "created": True}

    def fetch(self, job_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT job, COALESCE(action, ''), COALESCE(status, ''), COALESCE(log, ''), "
                    "started, finished, COALESCE(backend, ''), COALESCE(host(device)::text, '') "
                    "FROM admin WHERE job = %s",
                    (int(job_id),),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _view(row[0], row[7], row[1], row[2], row[3], row[4], row[6])

    def release_skipped(self, ip: str, action: str) -> bool:
        """Finish jobs Netdisco will never run.

        Discover records macsuck/arpnip/nbtstat on ``device_skip.actionset`` when
        the device has no bridging or routing layer. Those rows stay ``queued``
        with no backend forever, so the UI would poll until it gave up.
        """
        if action not in _ACTIONS:
            return False
        message = "Netdisco skipped %s for this device." % action
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE admin SET status = 'done', finished = LOCALTIMESTAMP, log = %s "
                    "WHERE device = %s::inet AND action = %s AND status = 'queued' AND backend IS NULL "
                    "AND EXISTS (SELECT 1 FROM device_skip WHERE device = %s::inet AND %s = ANY(actionset))",
                    (message, ip, action, ip, action),
                )
                changed = cur.rowcount > 0
            conn.commit()
        return changed

    def neighbour_ips(self, ip: str) -> list[str]:
        """CDP/LLDP neighbours Netdisco stored on ``device_port.remote_ip``."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT host(remote_ip)::text FROM device_port "
                        "WHERE ip = %s::inet AND remote_ip IS NOT NULL LIMIT 64",
                        (ip,),
                    )
                    found = [row[0] for row in cur.fetchall() if row and row[0]]
        except Exception:
            return []
        out = []
        for item in found:
            if item and item != ip and item not in out:
                out.append(item)
        return out[:32]
