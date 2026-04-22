"""CLI entrypoint for the dedicated OpenClaw backend ingress service."""

from __future__ import annotations

import logging
import os
import sys

from . import config
from .server import run_server


def _configure_logging() -> None:
    level_name = config.OPENCLAW_LOG_LEVEL.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)
    log.info(
        "openclaw_bootstrap_start pid=%s version=%s log_level=%s",
        os.getpid(),
        config.SERVICE_VERSION,
        config.OPENCLAW_LOG_LEVEL,
    )
    try:
        run_server()
    except Exception:
        log.exception("openclaw_bootstrap_failed")
        raise


if __name__ == "__main__":
    main()
