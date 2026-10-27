"""Run ie-config: python -m ie_config"""

import logging

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=int(__import__("os").environ.get("IE_CONFIG_PORT", "8080")),
                access_log=True, log_level="info")


if __name__ == "__main__":
    main()
