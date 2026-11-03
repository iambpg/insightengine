"""Add user-directory columns without touching password hashes.

``python -m ie_config.users_migrate`` is what scripts/upgrade.sh runs inside
ie-config. Starting ie-config runs the same function. Existing rows stay.
The earliest Administrator keeps the password hash it already has and becomes
the built-in ``admin`` account when that username is still free.
"""

from __future__ import annotations

import re

from sqlalchemy import inspect, text

from ie_config.db import make_engine
from ie_config.settings import Settings

BUILTIN_USERNAME = "admin"
_USERNAME = re.compile(r"[^a-z0-9._-]+")


def _slug(email: str, used: set[str]) -> str:
    local = (email or "").split("@", 1)[0].lower()
    cleaned = _USERNAME.sub("", local).strip(".-_")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = "user"
    cleaned = cleaned[:64]
    candidate = cleaned
    n = 2
    while candidate in used or candidate == BUILTIN_USERNAME:
        suffix = "-" + str(n)
        candidate = (cleaned[: 64 - len(suffix)] + suffix)
        n += 1
    used.add(candidate)
    return candidate


def ensure_user_schema(engine=None) -> None:
    engine = engine or make_engine(Settings.from_env().database_url)
    insp = inspect(engine)
    if not insp.has_table("users"):
        return
    columns = {col["name"] for col in insp.get_columns("users")}
    statements = []
    if "username" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(64)")
    if "display_name" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN display_name VARCHAR(120) DEFAULT ''")
    if "status" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN status VARCHAR(16) DEFAULT 'active'")
    if "last_login_at" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP")
    if "must_change_password" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    if "builtin" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN builtin INTEGER DEFAULT 0")
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        rows = conn.execute(text(
            "SELECT id, email, role, username, display_name, status, builtin FROM users ORDER BY id"
        )).mappings().all()
        used = {str(row["username"]).lower() for row in rows if row["username"]}
        for row in rows:
            sets = []
            params = {"id": row["id"]}
            if not row["username"]:
                username = _slug(row["email"] or "", used)
                sets.append("username = :username")
                params["username"] = username
            if row["display_name"] is None:
                sets.append("display_name = ''")
            if not row["status"]:
                sets.append("status = 'active'")
            if row["builtin"] is None:
                sets.append("builtin = 0")
            if sets:
                conn.execute(text("UPDATE users SET " + ", ".join(sets) + " WHERE id = :id"), params)
        # The built-in admin is the earliest Administrator. Its password is not in this UPDATE.
        current = conn.execute(text(
            "SELECT id, username, role FROM users ORDER BY id"
        )).mappings().all()
        protected = next((row for row in current if (row["username"] or "") == BUILTIN_USERNAME), None)
        earliest = next((row for row in current if row["role"] in ("Administrator", "Admin")), None)
        if protected is not None and protected["role"] not in ("Administrator", "Admin") and earliest is not None:
            taken = {str(row["username"]).lower() for row in current if row["username"]}
            taken.discard(BUILTIN_USERNAME)
            renamed = _slug("moved-admin@local", taken)
            conn.execute(
                text("UPDATE users SET username = :username, builtin = 0 WHERE id = :id"),
                {"username": renamed, "id": protected["id"]},
            )
            protected = None
        if protected is None and earliest is not None:
            conn.execute(
                text("UPDATE users SET username = :username, builtin = 1 WHERE id = :id"),
                {"username": BUILTIN_USERNAME, "id": earliest["id"]},
            )
        elif protected is not None and protected["role"] in ("Administrator", "Admin"):
            conn.execute(text("UPDATE users SET builtin = 1 WHERE id = :id"), {"id": protected["id"]})
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))
        _install_guard(conn, engine.dialect.name)


def _install_guard(conn, dialect: str) -> None:
    """Reject deleting, disabling, or demoting the username ``admin`` row."""
    if dialect == "postgresql":
        conn.execute(text(
            """
            CREATE OR REPLACE FUNCTION ie_protect_builtin_admin() RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                IF OLD.username = 'admin' THEN
                  RAISE EXCEPTION 'builtin admin cannot be deleted, disabled, or demoted';
                END IF;
                RETURN OLD;
              END IF;
              IF OLD.username = 'admin' AND (
                NEW.role NOT IN ('Administrator', 'Admin')
                OR NEW.status NOT IN ('active', 'enabled')
                OR NEW.username IS DISTINCT FROM 'admin'
              ) THEN
                RAISE EXCEPTION 'builtin admin cannot be deleted, disabled, or demoted';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        ))
        conn.execute(text("DROP TRIGGER IF EXISTS ie_users_protect_admin_upd ON users"))
        conn.execute(text("DROP TRIGGER IF EXISTS ie_users_protect_admin_del ON users"))
        conn.execute(text(
            """
            CREATE TRIGGER ie_users_protect_admin_upd
            BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE PROCEDURE ie_protect_builtin_admin()
            """
        ))
        conn.execute(text(
            """
            CREATE TRIGGER ie_users_protect_admin_del
            BEFORE DELETE ON users
            FOR EACH ROW EXECUTE PROCEDURE ie_protect_builtin_admin()
            """
        ))
        return
    conn.execute(text("DROP TRIGGER IF EXISTS ie_users_protect_admin_upd"))
    conn.execute(text("DROP TRIGGER IF EXISTS ie_users_protect_admin_del"))
    conn.execute(text(
        """
        CREATE TRIGGER ie_users_protect_admin_upd
        BEFORE UPDATE ON users
        FOR EACH ROW
        WHEN OLD.username = 'admin' AND (
          NEW.role NOT IN ('Administrator', 'Admin')
          OR NEW.status NOT IN ('active', 'enabled')
          OR IFNULL(NEW.username, '') != 'admin'
        )
        BEGIN
          SELECT RAISE(ABORT, 'builtin admin cannot be deleted, disabled, or demoted');
        END
        """
    ))
    conn.execute(text(
        """
        CREATE TRIGGER ie_users_protect_admin_del
        BEFORE DELETE ON users
        FOR EACH ROW
        WHEN OLD.username = 'admin'
        BEGIN
          SELECT RAISE(ABORT, 'builtin admin cannot be deleted, disabled, or demoted');
        END
        """
    ))


def main() -> None:
    ensure_user_schema()
    print("users schema is current; existing password hashes were not changed")


if __name__ == "__main__":
    main()
