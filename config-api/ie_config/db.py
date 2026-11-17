"""SQLAlchemy models. The audit table is append-only: the API never updates or deletes rows."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Nullable until scripts/upgrade.sh backfills existing rows. The built-in
    # account is the row whose username is admin; its password_hash is never rewritten.
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    builtin: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_email: Mapped[str] = mapped_column(String(320), default="")
    role: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(64))
    app: Mapped[str] = mapped_column(String(64), default="")
    file_id: Mapped[str] = mapped_column(String(128), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(32), default="")
    source_ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class ReloadState(Base):
    __tablename__ = "reload_state"
    app: Mapped[str] = mapped_column(String(64), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ok: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")


class DiscoveryScan(Base):
    __tablename__ = "discovery_scans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveryDeviceJob(Base):
    """One typed-IP discover. Netdisco job ids live here; the admin table is theirs."""

    __tablename__ = "discovery_device_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    neighbours: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    message: Mapped[str] = mapped_column(Text, default="")
    discover_job: Mapped[int] = mapped_column(Integer, default=0)
    macsuck_job: Mapped[int] = mapped_column(Integer, default=0)
    arpnip_job: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    sysdescr: Mapped[str] = mapped_column(Text, default="")
    sysobjectid: Mapped[str] = mapped_column(String(256), default="")
    vendor: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|rejected
    netbox_device_id: Mapped[str] = mapped_column(String(32), default="")
    site_slug: Mapped[str] = mapped_column(String(64), default="")
    role_slug: Mapped[str] = mapped_column(String(64), default="")
    tenant_slug: Mapped[str] = mapped_column(String(128), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detail: Mapped[str] = mapped_column(Text, default="")


class NetbridgeJob(Base):
    """One sync, scan, or apply. Counts and errors only — never secret values."""

    __tablename__ = "netbridge_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(320), default="")
    status: Mapped[str] = mapped_column(String(16), default="done", index=True)
    counts: Mapped[str] = mapped_column(Text, default="")
    errors: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NetbridgeConflict(Base):
    __tablename__ = "netbridge_conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    left_label: Mapped[str] = mapped_column(String(200), default="")
    right_label: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|resolved|ignored
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetbridgePreview(Base):
    __tablename__ = "netbridge_previews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(320), default="")
    payload: Mapped[str] = mapped_column(Text, default="")
    applied: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetbridgeAp(Base):
    __tablename__ = "netbridge_aps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wlc: Mapped[str] = mapped_column(String(128), index=True, default="")
    name: Mapped[str] = mapped_column(String(128), index=True, default="")
    model: Mapped[str] = mapped_column(String(128), index=True, default="")
    serial: Mapped[str] = mapped_column(String(128), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    neighbor: Mapped[str] = mapped_column(String(200), default="")
    neighbor_port: Mapped[str] = mapped_column(String(128), default="")
    platform: Mapped[str] = mapped_column(String(32), default="")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NetbridgeEox(Base):
    __tablename__ = "netbridge_eox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    pid: Mapped[str] = mapped_column(String(128), default="", index=True)
    serial: Mapped[str] = mapped_column(String(128), default="")
    source: Mapped[str] = mapped_column(String(16), default="")
    netbox_id: Mapped[str] = mapped_column(String(32), default="")
    end_of_sale: Mapped[str] = mapped_column(String(32), default="")
    end_of_sw_maintenance: Mapped[str] = mapped_column(String(32), default="")
    end_of_security: Mapped[str] = mapped_column(String(32), default="")
    last_date_of_support: Mapped[str] = mapped_column(String(32), default="")
    migration_pid: Mapped[str] = mapped_column(String(128), default="")
    bucket: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def ensure_discovery_schema(engine) -> None:
    """Add columns that create_all does not add to a database that already exists."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "discovery_candidates" not in insp.get_table_names():
        return
    names = {column["name"] for column in insp.get_columns("discovery_candidates")}
    if "tenant_slug" in names:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE discovery_candidates ADD COLUMN tenant_slug VARCHAR(128) DEFAULT ''"))


def make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def make_session_factory(url: str):
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    # Import inside the function so db can finish defining models first.
    from .users_migrate import ensure_user_schema

    ensure_user_schema(engine)
    ensure_discovery_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True), engine
