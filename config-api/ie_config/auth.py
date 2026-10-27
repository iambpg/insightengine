"""Sessions, argon2id passwords, CSRF and role checks."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select

from .db import SessionRow, User, utcnow
from .errors import ApiError

ROLES = ("Administrator", "Engineer", "Operator", "Read-only")
SETTINGS_ROLES = {"Administrator", "Engineer"}
_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


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
            user = db.scalar(select(User).where(User.email == email_n)) if email_n else None
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
            user.failed_attempts = 0
            user.locked_until = None
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
            return {"token": raw, "csrf": csrf, "role": user.role, "email": user.email}

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
            if user is None:
                raise ApiError(401, "unauthorized", "login required")
            return user, row.csrf

    def create_user(self, email: str, password: str, role: str) -> User:
        if role not in ROLES:
            raise ApiError(400, "bad_role", "role must be one of: " + ", ".join(ROLES))
        email = validate_email(email)
        password = validate_password(password)
        with self.sf() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise ApiError(409, "exists", "a user with that email already exists")
            user = User(email=email, password_hash=hash_password(password), role=role, failed_attempts=0)
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    def user_count(self) -> int:
        with self.sf() as db:
            return len(db.scalars(select(User.id)).all())


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
