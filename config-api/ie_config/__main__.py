"""Run ie-config: python -m ie_config

``python -m ie_config reset-admin`` reads the new password from stdin and does
not log it. ``--status`` only reports whether the users table is empty.
``--create --email`` creates the first Administrator when it is empty.
``scripts/reset-admin-password.sh`` is the supported way to call it.
"""

import logging
import sys

import uvicorn

from .app import create_app
from .reset_admin import reset_admin
from .settings import Settings


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "reset-admin":
        raise SystemExit(reset_admin(sys.argv[2:]))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=int(__import__("os").environ.get("IE_CONFIG_PORT", "8080")),
                access_log=True, log_level="info")


if __name__ == "__main__":
    main()
