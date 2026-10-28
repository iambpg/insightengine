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
    while args:
        item = args.pop(0)
        if item == "--email":
            if not args:
                print("reset-admin: --email needs an address", file=sys.stderr)
                return 2
            email = args.pop(0)
        elif item in ("-h", "--help"):
            print("usage: python -m ie_config reset-admin [--email user@host]", file=sys.stderr)
            return 0
        else:
            print("reset-admin: unknown argument", file=sys.stderr)
            return 2
    password = sys.stdin.read()
    if password.endswith("\n"):
        password = password[:-1]
    settings = Settings.from_env()
    factory, _engine = make_session_factory(settings.database_url)
    try:
        result = Auth(factory, settings).reset_password(email or None, password, "local-reset")
    except ApiError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print("password reset for %s" % result["email"])
    return 0
