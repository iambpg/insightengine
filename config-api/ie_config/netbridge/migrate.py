"""Create NetBridge tables on the ie-config database.

``python -m ie_config.netbridge.migrate`` is what scripts/upgrade.sh runs inside
ie-config. Starting ie-config also creates the tables. Existing rows are left
in place. Nothing is deleted.
"""

from __future__ import annotations

from ie_config.db import Base, make_engine
from ie_config.settings import Settings


def migrate(url: str | None = None) -> None:
    settings = Settings.from_env()
    engine = make_engine(url or settings.database_url)
    # Importing db registers every model, including the NetBridge tables.
    Base.metadata.create_all(engine)


def main() -> None:
    migrate()
    print("netbridge tables are present")


if __name__ == "__main__":
    main()
