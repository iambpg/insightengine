"""Cisco Support EoX API v5.

OAuth2 client-credentials against id.cisco.com, then the supporttools EoX
resource. Client id, secret, and access token are never logged.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import httpx

from .plan import eox_bucket

log = logging.getLogger("ie-config.netbridge")

TOKEN_URL = "https://id.cisco.com/oauth2/default/v1/token"
EOX_ROOT = "https://apix.cisco.com/supporttools/eox/rest/5"
BATCH = 20
PROBE_PID = "WS-C2960-24TC-L"
MISSING = (
    "Cisco Support API credentials are not configured. "
    "Add the client id and secret in Settings → Vault."
)


def _date_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value") or ""
    text = str(value).strip()
    if not text or text.lower() in ("none", "null"):
        return ""
    return text[:10]


def record_fields(record: dict) -> dict:
    if not isinstance(record, dict):
        return {}
    error = record.get("EOXError") or {}
    if isinstance(error, dict) and str(error.get("ErrorID") or "") not in ("", "0", "None"):
        description = str(error.get("ErrorDescription") or "no EoX record")
        return {"message": description[:300]}
    migration = record.get("MigrationInformation") or {}
    if isinstance(migration, list):
        migration = migration[0] if migration else {}
    if not isinstance(migration, dict):
        migration = {}
    product = record.get("EOLProductID") or record.get("ProductID") or ""
    if isinstance(product, list):
        product = product[0] if product else ""
    return {
        "pid": str(product or "")[:128],
        "end_of_sale": _date_text(record.get("EndOfSaleDate") or record.get("EOXExternalAnnouncementDate")),
        "end_of_sw_maintenance": _date_text(record.get("EndOfSWMaintenanceReleases")),
        "end_of_security": _date_text(record.get("EndOfSecurityVulSupportDate")),
        "last_date_of_support": _date_text(record.get("LastDateOfSupport")),
        "migration_pid": str(migration.get("MigrationProductId") or "")[:128],
        "message": "",
    }


class EoxClient:
    def __init__(self, client_id: str = "", client_secret: str = "", http: httpx.Client | None = None, pause: float = 0.25):
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.http = http
        self.pause = pause
        self._token = ""
        self._token_until = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _client(self) -> httpx.Client:
        if self.http is not None:
            return self.http
        return httpx.Client(timeout=30.0)

    def _owned(self) -> bool:
        return self.http is None

    def token(self) -> str:
        if not self.configured:
            raise RuntimeError("not_configured")
        now = time.time()
        if self._token and now < self._token_until:
            return self._token
        url = os.environ.get("CISCO_API_TOKEN_URL") or TOKEN_URL
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        client = self._client()
        try:
            response = client.post(url, data=payload, headers={"Accept": "application/json"})
        finally:
            if self._owned():
                client.close()
        if response.status_code >= 400:
            log.warning("cisco oauth status %s", response.status_code)
            raise RuntimeError("cisco_auth")
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("cisco_auth")
        access = str(body.get("access_token") or "")
        if not access:
            log.warning("cisco oauth status %s without a token", response.status_code)
            raise RuntimeError("cisco_auth")
        try:
            expires = int(body.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires = 3600
        self._token = access
        self._token_until = now + max(60, expires - 60)
        return access

    def _get(self, path: str) -> dict:
        access = self.token()
        root = os.environ.get("CISCO_API_EOX_URL") or EOX_ROOT
        url = root.rstrip("/") + "/" + path.lstrip("/")
        client = self._client()
        try:
            response = client.get(url, headers={"Authorization": "Bearer " + access, "Accept": "application/json"})
        finally:
            if self._owned():
                client.close()
        if response.status_code >= 400:
            log.warning("cisco eox status %s", response.status_code)
            raise RuntimeError("cisco_eox")
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("cisco_eox")
        return body if isinstance(body, dict) else {}

    def lookup_products(self, pids: list[str]) -> dict[str, dict]:
        return self._lookup("EOXByProductID", pids, "pid")

    def lookup_serials(self, serials: list[str]) -> dict[str, dict]:
        return self._lookup("EOXBySerialNumber", serials, "serial")

    def _lookup(self, method: str, values: list[str], key: str) -> dict[str, dict]:
        found: dict[str, dict] = {}
        clean = []
        for value in values:
            text = (value or "").strip()
            if text and text not in clean:
                clean.append(text)
        for offset in range(0, len(clean), BATCH):
            chunk = clean[offset:offset + BATCH]
            if offset and self.pause:
                time.sleep(self.pause)
            joined = ",".join(chunk)
            try:
                body = self._get("%s/1/%s" % (method, joined))
            except RuntimeError:
                body = {}
                for one in chunk:
                    try:
                        single = self._get("%s/1/%s" % (method, one))
                    except RuntimeError:
                        found[one] = {"message": "EoX lookup failed", "bucket": "unknown"}
                        continue
                    self._absorb(single, chunk, key, found)
                continue
            self._absorb(body, chunk, key, found)
        return found

    def _absorb(self, body: dict, requested: list[str], key: str, found: dict) -> None:
        records = body.get("EOXRecord") or []
        if isinstance(records, dict):
            records = [records]
        used = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            fields = record_fields(record)
            fields["bucket"] = eox_bucket(fields.get("last_date_of_support") or "", date.today())
            ident = ""
            if key == "pid":
                ident = fields.get("pid") or ""
            else:
                ident = str(record.get("SerialNumber") or record.get("EOXInputValue") or "")
            if not ident and len(requested) == 1:
                ident = requested[0]
            if ident:
                found[ident] = fields
                used.add(ident)
        for value in requested:
            if value not in found and value not in used:
                found.setdefault(value, {"message": "No EoX record", "bucket": "unknown"})

    def probe(self) -> dict:
        if not self.configured:
            return {"ok": False, "message": MISSING}
        try:
            self.token()
        except RuntimeError:
            return {"ok": False, "message": "Cisco rejected the client credentials."}
        try:
            self.lookup_products([PROBE_PID])
        except RuntimeError:
            return {"ok": True, "message": "Token works. The sample product lookup did not complete."}
        return {"ok": True, "message": "Token works. Sample EoX lookup for %s completed." % PROBE_PID}
