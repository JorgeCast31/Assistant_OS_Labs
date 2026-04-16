"""Standalone runner for the control-plane scheduler outside the admin server lifecycle."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import signal
import time

from ..config import CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS
from .scheduler import ControlPlaneScheduler

logger = logging.getLogger("assistant_os.control_plane.scheduler_runner")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AssistantOS standalone control-plane scheduler runner")
    parser.add_argument("--interval-seconds", type=int, default=CONTROL_PLANE_SCHEDULER_INTERVAL_SECONDS)
    parser.add_argument("--run-once", action="store_true", help="Run one maintenance cycle and exit")
    parser.add_argument("--duration-seconds", type=int, default=0, help="Run for a fixed duration and exit")
    return parser


def _configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )


def _status_payload(scheduler: ControlPlaneScheduler, *, mode: str) -> dict:
    payload = scheduler.status()
    payload["mode"] = mode
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging()
    scheduler = ControlPlaneScheduler(interval_seconds=args.interval_seconds)
    scheduler.last_host_mode = "standalone_scheduler_runner"

    def _stop_handler(signum, frame):  # noqa: ANN001,ARG001
        scheduler.stop(wait=False)

    signal.signal(signal.SIGTERM, _stop_handler)
    signal.signal(signal.SIGINT, _stop_handler)

    if args.run_once:
        record = scheduler.run_once()
        print(json.dumps({"status": "ok", "run": asdict(record), "scheduler": scheduler.status()}, indent=2))
        return 0

    scheduler.start()
    started = time.monotonic()
    try:
        while scheduler.is_running():
            if args.duration_seconds and (time.monotonic() - started) >= args.duration_seconds:
                break
            time.sleep(0.1)
    finally:
        scheduler.stop(wait=True)
    print(json.dumps({"status": "stopped", "scheduler": _status_payload(scheduler, mode="standalone")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
