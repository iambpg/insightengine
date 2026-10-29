"""`python -m ie_config reset-admin`. The password is read from stdin and not logged."""

from __future__ import annotations

import sys

from .auth import Auth
from .db import make_session_factory
from .errors import ApiError
from .settings import Settings


def reset_admin(argv: list[str] | None = None) -> int:
    args = list(sys.argv[2:] if argv is None else argv)
    email = ""
    create = False
    status_only = False
    while args:
        item = args.pop(0)
        if item == "--email":
            if not args:
                print("reset-admin: --email needs an address", file=sys.stderr)
                return 2
            email = args.pop(0)
        elif item == "--create":
            create = True
        elif item == "--status":
            status_only = True
        elif item in ("-h", "--help"):
            print(
                "usage: python -m ie_config reset-admin [--status | --create --email user@host | --email user@host]",
                file=sys.stderr,
            )
            return 0
        else:
            print("reset-admin: unknown argument", file=sys.stderr)
            return 2
    if status_only and create:
        print("reset-admin: --status does not take --create", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    factory, _engine = make_session_factory(settings.database_url)
    auth = Auth(factory, settings)
    if status_only:
        # No password is read. The line is empty, users, or admin <email>.
        print(auth.account_status())
        return 0
    if create and not email:
        print("reset-admin: --create needs --email", file=sys.stderr)
        return 2
    password = sys.stdin.read()
    if password.endswith("\n"):
        password = password[:-1]
    try:
        if create:
            result = auth.create_first_admin(email, password, "local-reset")
        else:
            result = auth.reset_password(email or None, password, "local-reset")
    except ApiError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    if create:
        print("administrator created for %s" % result["email"])
    else:
        print("password reset for %s" % result["email"])
    return 0
