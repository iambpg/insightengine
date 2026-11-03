"""Sessions, argon2id passwords, CSRF and role checks."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError, IntegrityError

from .db import AuditRow, SessionRow, User, utcnow
from .errors import ApiError
from .users_migrate import BUILTIN_USERNAME

# Stored roles stay the ones the rest of the API already understands.
# Admin and Viewer are accepted names for Administrator and Read-only.
ROLES = ("Administrator", "Engineer", "Operator", "Read-only")
SETTINGS_ROLES = {"Administrator", "Engineer"}
_ROLE_ALIASES = {
    "admin": "Administrator",
    "administrator": "Administrator",
    "engineer": "Engineer",
    "operator": "Operator",
    "viewer": "Read-only",
    "read-only": "Read-only",
    "readonly": "Read-only",
}
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
USER_AUDIT_ACTIONS = (
    "user-create", "user-update", "user-disable", "user-enable",
    "user-delete", "user-password-reset", "user-password-change",
    "create-user", "bootstrap-admin", "password-reset", "admin-created",
)
_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def canonical_role(role: str) -> str:
    return _ROLE_ALIASES.get((role or "").strip().lower(), role or "")


def normalize_role(role: str) -> str:
    chosen = canonical_role(role if isinstance(role, str) else "")
    if chosen not in ROLES:
        raise ApiError(400, "bad_role", "role must be one of: Admin, Operator, Viewer, Engineer")
    return chosen


def is_admin(role: str) -> bool:
    return canonical_role(role) == "Administrator"


def can_settings(role: str) -> bool:
    return canonical_role(role) in ("Administrator", "Engineer")


def can_operate(role: str) -> bool:
    """NetBridge writes, alert acknowledgement, and device edits."""
    return canonical_role(role) in ("Administrator", "Engineer", "Operator")


def role_in(role: str, allowed) -> bool:
    canon = canonical_role(role)
    return any(canonical_role(item) == canon and canon for item in allowed)


def is_builtin_admin(user) -> bool:
    return (getattr(user, "username", None) or "") == BUILTIN_USERNAME or bool(getattr(user, "builtin", 0))


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _ph.verify(encoded, password)
    except VerifyMismatchError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_email(email: str) -> str:
    if not isinstance(email, str):
        raise ApiError(400, "bad_email", "email must be a string")
    email = email.strip().lower()
    if not (3 <= len(email) <= 320) or email.count("@") != 1:
        raise ApiError(400, "bad_email", "email is not valid")
    local, _, domain = email.partition("@")
    if not local or "." not in domain or any(c.isspace() for c in email):
        raise ApiError(400, "bad_email", "email is not valid")
    return email


def validate_password(password: str) -> str:
    if not isinstance(password, str) or not (12 <= len(password) <= 200):
        raise ApiError(400, "bad_password", "password must be 12-200 characters")
    if any(ord(c) < 32 for c in password):
        raise ApiError(400, "bad_password", "password must not contain control characters")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ApiError(400, "bad_password", "password needs a letter and a digit")
    return password


def validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise ApiError(400, "bad_username", "username must be a string")
    username = username.strip().lower()
    if not _USERNAME.match(username):
        raise ApiError(
            400, "bad_username",
            "username must start with a letter or digit and use only letters, digits, dots, underscores, or hyphens",
        )
    return username


def validate_display_name(name: str) -> str:
    if not isinstance(name, str):
        raise ApiError(400, "bad_name", "name must be a string")
    name = name.strip()
    if not (1 <= len(name) <= 120):
        raise ApiError(400, "bad_name", "name must be 1-120 characters")
    if any(ord(c) < 32 for c in name):
        raise ApiError(400, "bad_name", "name must not contain control characters")
    return name


def generate_password() -> str:
    """A one-time password that already satisfies the strength rules."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(20))
        if any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw):
            return raw


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def user_public(user) -> dict:
    """Fields safe to return. The password hash is never included."""
    return {
        "id": user.id,
        "username": user.username or "",
        "displayName": user.display_name or "",
        "email": user.email,
        "role": user.role,
        "status": user.status or "active",
        "lastLogin": _iso(user.last_login_at),
        "created": _iso(user.created_at),
        "builtin": is_builtin_admin(user),
        "mustChangePassword": bool(user.must_change_password),
    }


def read_setup_token(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def check_bearer(header: str, token: str) -> bool:
    if not token or not header.startswith("Bearer "):
        return False
    got = header[7:].strip()
    return hmac.compare_digest(got.encode(), token.encode())


class Auth:
    def __init__(self, session_factory, settings):
        self.sf = session_factory
        self.settings = settings
        self._ip_fails: dict[str, list[float]] = {}

    def _ip_limited(self, ip: str) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        recent = [t for t in self._ip_fails.get(ip, []) if now - t < 60]
        self._ip_fails[ip] = recent
        if len(recent) >= 30:
            return True
        return False

    def _note_ip(self, ip: str) -> None:
        self._ip_fails.setdefault(ip, []).append(datetime.now(timezone.utc).timestamp())

    def login(self, email: str, password: str, ip: str) -> dict:
        if self._ip_limited(ip):
            raise ApiError(429, "rate_limited", "too many login attempts from this address; wait a minute")
        email_n = email.strip().lower() if isinstance(email, str) else ""
        with self.sf() as db:
            user = self._find_login(db, email_n)
            now = utcnow()
            if user and user.locked_until is not None:
                locked = user.locked_until
                if locked.tzinfo is None:
                    locked = locked.replace(tzinfo=timezone.utc)
                if locked > now:
                    self._note_ip(ip)
                    raise ApiError(429, "locked", "this account is locked after repeated failures; try again later")
            if user is None or not isinstance(password, str) or not verify_password(password, user.password_hash):
                self._note_ip(ip)
                if user is not None:
                    user.failed_attempts = (user.failed_attempts or 0) + 1
                    if user.failed_attempts >= self.settings.lockout_failures:
                        user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
                        user.failed_attempts = 0
                    db.commit()
                raise ApiError(401, "invalid_credentials", "invalid email or password")
            if (user.status or "active") != "active":
                self._note_ip(ip)
                raise ApiError(403, "disabled", "this account is disabled")
            user.failed_attempts = 0
            user.locked_until = None
            user.last_login_at = now
            raw = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(24)
            row = SessionRow(
                token_hash=token_hash(raw),
                user_id=user.id,
                csrf=csrf,
                expires_at=now + timedelta(hours=self.settings.session_hours),
            )
            db.add(row)
            db.commit()
            return {
                "token": raw,
                "csrf": csrf,
                "role": user.role,
                "email": user.email,
                "username": user.username or "",
                "displayName": user.display_name or "",
                "id": user.id,
                "mustChangePassword": bool(user.must_change_password),
            }

    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        with self.sf() as db:
            row = db.get(SessionRow, token_hash(raw_token))
            if row:
                db.delete(row)
                db.commit()

    def session_user(self, raw_token: str | None):
        if not raw_token:
            raise ApiError(401, "unauthorized", "login required")
        with self.sf() as db:
            row = db.get(SessionRow, token_hash(raw_token))
            if row is None:
                raise ApiError(401, "unauthorized", "login required")
            exp = row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < utcnow():
                db.delete(row)
                db.commit()
                raise ApiError(401, "unauthorized", "session expired")
            user = db.get(User, row.user_id)
            if user is None or (user.status or "active") != "active":
                raise ApiError(401, "unauthorized", "login required")
            return user, row.csrf

    def create_user(
        self,
        email: str,
        password: str,
        role: str,
        username: str | None = None,
        display_name: str = "",
        must_change: bool = False,
        builtin: bool = False,
    ) -> User:
        role = normalize_role(role)
        email = validate_email(email)
        password = validate_password(password)
        with self.sf() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise ApiError(409, "exists", "a user with that email already exists")
            chosen = validate_username(username) if username else self._username_for(db, email)
            if chosen == BUILTIN_USERNAME and not builtin:
                raise ApiError(409, "reserved", "the username admin is reserved for the built-in account")
            if db.scalar(select(User).where(User.username == chosen)):
                raise ApiError(409, "exists", "a user with that username already exists")
            user = User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                failed_attempts=0,
                username=chosen,
                display_name=validate_display_name(display_name) if display_name else chosen,
                status="active",
                must_change_password=1 if must_change else 0,
                builtin=1 if builtin or chosen == BUILTIN_USERNAME else 0,
            )
            db.add(user)
            self._commit(db)
            db.refresh(user)
            db.expunge(user)
            return user

    def user_count(self) -> int:
        with self.sf() as db:
            return len(db.scalars(select(User.id)).all())

    def account_status(self) -> str:
        """One line for the reset script: ``empty``, ``users``, or ``admin <email>``."""
        with self.sf() as db:
            if self._no_users(db):
                return "empty"
            user = self._first_admin(db)
            if user is None:
                return "users"
            return "admin " + user.email

    def create_first_admin(self, email: str, password: str, ip: str) -> dict:
        """Create the Administrator when the users table is empty.

        The password is hashed and is not written into the audit row.
        """
        email = validate_email(email)
        password = validate_password(password)
        with self.sf() as db:
            if not self._no_users(db):
                raise ApiError(
                    409, "already_bootstrapped",
                    "users already exist; reset a password instead of creating one",
                )
            user = User(
                email=email,
                password_hash=hash_password(password),
                role="Administrator",
                failed_attempts=0,
                username=BUILTIN_USERNAME,
                display_name="Administrator",
                status="active",
                must_change_password=0,
                builtin=1,
            )
            db.add(user)
            db.flush()
            db.add(AuditRow(
                user_email=user.email,
                role="Administrator",
                action="admin-created",
                app="ie-config",
                result="ok",
                source_ip=(ip or "")[:64],
                detail="first administrator created",
            ))
            db.commit()
            return {"email": user.email}

    def reset_password(self, email: str | None, password: str, ip: str) -> dict:
        """Replace one user's password. The password is not stored in the audit row."""
        password = validate_password(password)
        email_n = validate_email(email) if email else ""
        with self.sf() as db:
            if email_n:
                user = db.scalar(select(User).where(User.email == email_n))
                if user is None:
                    if self._no_users(db):
                        raise ApiError(
                            409, "no_users",
                            "no users exist yet; re-run reset-admin-password.sh so it can create the administrator",
                        )
                    raise ApiError(404, "no_user", "no user with that email")
            else:
                user = self._first_admin(db)
                if user is None:
                    if self._no_users(db):
                        raise ApiError(
                            409, "no_users",
                            "no users exist yet; re-run reset-admin-password.sh so it can create the administrator",
                        )
                    raise ApiError(404, "no_admin", "no Administrator exists; pass --email")
            user.password_hash = hash_password(password)
            user.failed_attempts = 0
            user.locked_until = None
            db.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
            db.add(AuditRow(
                user_email=user.email,
                role=user.role,
                action="password-reset",
                app="ie-config",
                result="ok",
                source_ip=(ip or "")[:64],
                detail="sessions cleared",
            ))
            db.commit()
            return {"email": user.email}

    def list_directory(self) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(select(User).order_by(User.id)).all()
            return [user_public(row) for row in rows]

    def user_audit(self) -> list[dict]:
        with self.sf() as db:
            rows = db.scalars(
                select(AuditRow).where(AuditRow.action.in_(USER_AUDIT_ACTIONS)).order_by(AuditRow.id.desc()).limit(100)
            ).all()
            return [{
                "id": row.id,
                "at": _iso(row.ts),
                "actor": row.user_email,
                "role": row.role,
                "action": row.action,
                "detail": row.detail or row.comment or "",
                "result": row.result,
            } for row in rows]

    def update_user(self, actor, user_id: int, body: dict, ip: str) -> dict:
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        with self.sf() as db:
            target = self._require_user(db, user_id)
            changes = []
            if "displayName" in body or "name" in body:
                target.display_name = validate_display_name(body.get("displayName", body.get("name", "")))
                changes.append("name")
            if "email" in body:
                email = validate_email(body.get("email", ""))
                other = db.scalar(select(User).where(User.email == email, User.id != target.id))
                if other is not None:
                    raise ApiError(409, "exists", "a user with that email already exists")
                target.email = email
                changes.append("email")
            if "role" in body:
                role = normalize_role(body.get("role", ""))
                if role != target.role:
                    self._guard_admin(db, target, new_role=role)
                    target.role = role
                    changes.append("role")
            if not changes:
                return user_public(target)
            self._audit(db, actor, "user-update", ip, target.username + " " + ",".join(changes))
            self._commit(db)
            db.refresh(target)
            return user_public(target)

    def set_status(self, actor, user_id: int, status: str, ip: str) -> dict:
        if status not in ("active", "disabled"):
            raise ApiError(400, "bad_status", "status must be active or disabled")
        with self.sf() as db:
            target = self._require_user(db, user_id)
            if (target.status or "active") == status:
                return user_public(target)
            if status != "active":
                self._guard_admin(db, target, new_status=status)
            target.status = status
            if status != "active":
                db.execute(delete(SessionRow).where(SessionRow.user_id == target.id))
            self._audit(db, actor, "user-disable" if status != "active" else "user-enable", ip, target.username or "")
            self._commit(db)
            db.refresh(target)
            return user_public(target)

    def delete_user(self, actor, user_id: int, ip: str) -> None:
        with self.sf() as db:
            target = self._require_user(db, user_id)
            if target.id == getattr(actor, "id", None):
                raise ApiError(403, "self_delete", "you cannot delete your own account")
            self._guard_admin(db, target, deleting=True)
            username = target.username or ""
            email = target.email
            db.execute(delete(SessionRow).where(SessionRow.user_id == target.id))
            db.delete(target)
            self._audit(db, actor, "user-delete", ip, username + " " + email)
            self._commit(db)

    def reset_user_password(self, actor, user_id: int, body: dict, ip: str) -> dict:
        if not isinstance(body, dict):
            raise ApiError(400, "bad_body", "body must be a JSON object")
        generated = ""
        if body.get("generate") is True:
            generated = generate_password()
            password = generated
        else:
            password = validate_password(body.get("password", ""))
        with self.sf() as db:
            target = self._require_user(db, user_id)
            target.password_hash = hash_password(password)
            target.failed_attempts = 0
            target.locked_until = None
            target.must_change_password = 1
            db.execute(delete(SessionRow).where(SessionRow.user_id == target.id))
            # The password itself is not written into the audit row.
            self._audit(db, actor, "user-password-reset", ip, (target.username or "") + " sessions cleared")
            self._commit(db)
            result = {"ok": True, "username": target.username or "", "mustChangePassword": True}
            if generated:
                result["oneTimePassword"] = generated
            return result

    def change_password(self, user_id: int, current: str, new_password: str, ip: str) -> None:
        new_password = validate_password(new_password)
        if not isinstance(current, str):
            raise ApiError(400, "bad_password", "password must be 12-200 characters")
        with self.sf() as db:
            target = self._require_user(db, user_id)
            if not verify_password(current, target.password_hash):
                raise ApiError(401, "invalid_credentials", "invalid email or password")
            target.password_hash = hash_password(new_password)
            target.must_change_password = 0
            target.failed_attempts = 0
            target.locked_until = None
            self._audit(db, target, "user-password-change", ip, target.username or "")
            self._commit(db)

    def _guard_admin(self, db, target, new_role: str | None = None, new_status: str | None = None, deleting: bool = False) -> None:
        demote = new_role is not None and not is_admin(new_role)
        disable = new_status is not None and new_status != "active"
        if is_builtin_admin(target) and (deleting or demote or disable or (new_role is not None and new_role != target.role and not is_admin(new_role))):
            raise ApiError(409, "protected_admin", "the built-in admin account cannot be deleted, disabled, or demoted")
        if is_builtin_admin(target) and (deleting or disable or (new_role is not None and not is_admin(new_role))):
            raise ApiError(409, "protected_admin", "the built-in admin account cannot be deleted, disabled, or demoted")
        removing_admin = is_admin(target.role) and (target.status or "active") == "active" and (deleting or demote or disable)
        if removing_admin and self._other_active_admins(db, target.id) < 1:
            raise ApiError(409, "last_admin", "the last administrator cannot be removed, disabled, or demoted")

    @staticmethod
    def _other_active_admins(db, exclude_id: int) -> int:
        rows = db.scalars(select(User)).all()
        return sum(
            1 for row in rows
            if row.id != exclude_id and is_admin(row.role) and (row.status or "active") == "active"
        )

    @staticmethod
    def _first_admin(db):
        rows = db.scalars(select(User).order_by(User.id)).all()
        for row in rows:
            if is_admin(row.role):
                return row
        return None

    @staticmethod
    def _find_login(db, identity: str):
        if not identity:
            return None
        user = db.scalar(select(User).where(User.email == identity))
        if user is None:
            user = db.scalar(select(User).where(User.username == identity))
        return user

    @staticmethod
    def _require_user(db, user_id: int) -> User:
        try:
            key = int(user_id)
        except (TypeError, ValueError):
            raise ApiError(404, "no_user", "no user with that id")
        user = db.get(User, key)
        if user is None:
            raise ApiError(404, "no_user", "no user with that id")
        return user

    def _username_for(self, db, email: str) -> str:
        local = email.split("@", 1)[0]
        cleaned = re.sub(r"[^a-z0-9._-]", "", local)[:64]
        if not cleaned or not cleaned[0].isalnum():
            cleaned = "user"
        candidate = cleaned
        n = 2
        while candidate == BUILTIN_USERNAME or db.scalar(select(User.id).where(User.username == candidate)):
            suffix = "-" + str(n)
            candidate = cleaned[: 64 - len(suffix)] + suffix
            n += 1
        return candidate

    def _audit(self, db, actor, action: str, ip: str, detail: str) -> None:
        db.add(AuditRow(
            user_email=getattr(actor, "email", "") or "",
            role=getattr(actor, "role", "") or "",
            action=action,
            app="users",
            result="ok",
            source_ip=(ip or "")[:64],
            detail=(detail or "")[:2000],
        ))

    def _commit(self, db) -> None:
        try:
            db.commit()
        except (IntegrityError, DatabaseError) as exc:
            db.rollback()
            text = str(getattr(exc, "orig", exc)).lower()
            if "builtin admin" in text:
                raise ApiError(409, "protected_admin", "the built-in admin account cannot be deleted, disabled, or demoted")
            raise

    @staticmethod
    def _no_users(db) -> bool:
        return db.scalar(select(User.id)) is None


def client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host
    return ""


def require_csrf(header_value: str, csrf: str) -> None:
    if not header_value or not hmac.compare_digest(header_value.encode(), csrf.encode()):
        raise ApiError(403, "csrf", "missing or invalid CSRF token")
