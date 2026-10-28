"""Password reset does not keep the password in the audit row."""

import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "config-api"))

from ie_config.auth import Auth, verify_password  # noqa: E402
from ie_config.db import AuditRow, SessionRow, User, make_session_factory, utcnow  # noqa: E402
from ie_config.errors import ApiError  # noqa: E402
from ie_config.settings import Settings  # noqa: E402


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        config_root=str(tmp_path),
        apps_file=str(tmp_path / "apps.yml"),
        database_url="sqlite:///" + str(tmp_path / "ie.db"),
        history_dir=str(tmp_path / "history"),
        cookie_secure=False,
        cookie_name="ie_session",
        setup_token_file=str(tmp_path / "setup"),
        client_slug="test",
        public_host="localhost",
        docker_proxy_url="http://127.0.0.1:9",
        scheduler=False,
        netbox_url="http://127.0.0.1:9",
        netbox_token_file=str(tmp_path / "token"),
        netdisco_database_url="",
        netdisco_out_dir=str(tmp_path / "nd"),
        mib_dir=str(tmp_path / "mibs"),
        candidate_dir=str(tmp_path / "cand"),
        generator_bin="generator",
    )


def test_reset_clears_lock_and_sessions_without_storing_the_password(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = _settings(tmp_path)
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    auth.create_user("eng@example.com", "EngineerPass12", "Engineer")
    admin = auth.create_user("admin@example.com", "OldPassword12", "Administrator")
    with factory() as db:
        user = db.get(User, admin.id)
        user.failed_attempts = 4
        user.locked_until = utcnow() + timedelta(minutes=15)
        db.add(SessionRow(token_hash="abc", user_id=admin.id, csrf="csrf", expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    new_password = "NewPassword99"
    result = auth.reset_password(None, new_password, "local-reset")
    assert result == {"email": "admin@example.com"}
    with factory() as db:
        user = db.get(User, admin.id)
        assert verify_password(new_password, user.password_hash)
        assert not verify_password("OldPassword12", user.password_hash)
        assert user.failed_attempts == 0
        assert user.locked_until is None
        assert db.get(SessionRow, "abc") is None
        row = db.query(AuditRow).one()
        assert row.action == "password-reset"
        assert row.user_email == "admin@example.com"
        blob = " ".join([row.detail or "", row.comment or "", row.file_id or ""])
        assert new_password not in blob
    chosen = auth.reset_password("eng@example.com", "EngineerPass99", "local-reset")
    assert chosen["email"] == "eng@example.com"


def test_reset_refuses_an_empty_database(tmp_path):
    settings = _settings(tmp_path)
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    try:
        auth.reset_password(None, "NewPassword99", "local-reset")
    except ApiError as exc:
        assert exc.code == "no_users"
        assert "reset-admin-password.sh" in exc.message
        assert "/setup/" not in exc.message
    else:
        raise AssertionError("empty database was reset")


def test_create_first_admin_when_users_is_empty(tmp_path):
    settings = _settings(tmp_path)
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    assert auth.account_status() == "empty"
    password = "FirstAdmin99"
    created = auth.create_first_admin("admin@example.com", password, "local-reset")
    assert created == {"email": "admin@example.com"}
    assert auth.account_status() == "admin admin@example.com"
    with factory() as db:
        user = db.query(User).one()
        assert user.role == "Administrator"
        assert verify_password(password, user.password_hash)
        row = db.query(AuditRow).one()
        assert row.action == "admin-created"
        blob = " ".join([row.detail or "", row.comment or "", row.file_id or ""])
        assert password not in blob
    try:
        auth.create_first_admin("other@example.com", "SecondAdmin99", "local-reset")
    except ApiError as exc:
        assert exc.code == "already_bootstrapped"
    else:
        raise AssertionError("a second administrator was created over existing users")


def test_reset_uses_the_same_password_rules(tmp_path):
    settings = _settings(tmp_path)
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    auth.create_user("admin@example.com", "OldPassword12", "Administrator")
    try:
        auth.reset_password(None, "short", "local-reset")
    except ApiError as exc:
        assert exc.code == "bad_password"
    else:
        raise AssertionError("short password was accepted")
    with factory() as db:
        user = db.query(User).one()
        assert verify_password("OldPassword12", user.password_hash)


def test_ie_config_logs_complete_setup_with_no_users(tmp_path, caplog):
    settings = _settings(tmp_path)
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    from ie_config.app import warn_complete_setup_without_users
    warn_complete_setup_without_users(settings, auth)
    setup = tmp_path / "data" / "setup"
    setup.mkdir(parents=True)
    (setup / "config.json").write_text(json.dumps({"state": "unconfigured"}), encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        warn_complete_setup_without_users(settings, auth)
    assert caplog.text == ""
    (setup / "config.json").write_text(json.dumps({"state": "complete"}), encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        warn_complete_setup_without_users(settings, auth)
    assert "users table is empty" in caplog.text
    auth.create_user("admin@example.com", "OldPassword12", "Administrator")
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        warn_complete_setup_without_users(settings, auth)
    assert caplog.text == ""


def test_cli_creates_when_empty_and_does_not_print_the_password(tmp_path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("CONFIG_ROOT", settings.config_root)
    from ie_config.reset_admin import reset_admin
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("BrandNewPass1"))
    code = reset_admin(["--status"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "empty"
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("BrandNewPass1\n"))
    code = reset_admin(["--create", "--email", "admin@example.com"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "administrator created for admin@example.com"
    assert "BrandNewPass1" not in captured.out
    assert "BrandNewPass1" not in captured.err


def test_cli_reads_stdin_and_does_not_print_the_password(tmp_path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("CONFIG_ROOT", settings.config_root)
    factory, _engine = make_session_factory(settings.database_url)
    Auth(factory, settings).create_user("admin@example.com", "OldPassword12", "Administrator")
    from ie_config.reset_admin import reset_admin
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("BrandNewPass1\n"))
    code = reset_admin([])
    captured = capsys.readouterr()
    assert code == 0
    assert "BrandNewPass1" not in captured.out
    assert "BrandNewPass1" not in captured.err
    assert "admin@example.com" in captured.out
