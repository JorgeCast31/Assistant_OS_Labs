"""Lightweight internal scheduler for autonomous control-plane maintenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
import threading

from ..contracts import now_iso
from .maintenance import emit_operational_signal, run_maintenance_cycle

logger = logging.getLogger("assistant_os.control_plane")


@dataclass(slots=True)
class SchedulerRunRecord:
    """Represents the outcome of a scheduler maintenance run."""

    run_id: str
    started_at: str
    finished_at: str
    cleaned_tokens: int
    cleaned_store_records: dict[str, int]
    cleaned_lock_slots: int
    warnings: list[str]


class ControlPlaneScheduler:
    """Deterministic maintenance loop for the standalone control plane."""

    def __init__(self, *, interval_seconds: int = 60, runner=None) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.started_at = ""
        self.last_started_at = ""
        self.last_finished_at = ""
        self.last_run: SchedulerRunRecord | None = None
        self.run_count = 0
        self.last_failure = ""
        self.last_host_mode = "in_process_thread"
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._state_guard = threading.RLock()
        self._runner = runner or run_maintenance_cycle

    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and not self._stop_event.is_set())

    def start(self) -> None:
        with self._state_guard:
            if self.is_running():
                return
            self._stop_event.clear()
            self.started_at = self.started_at or now_iso()
            self._thread = threading.Thread(
                target=self._loop,
                name="assistant-os-control-plane-scheduler",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "control_plane.scheduler.started",
            extra={"event": "control_plane.scheduler.started", "interval_seconds": self.interval_seconds},
        )

    def stop(self, *, wait: bool = True) -> None:
        self._stop_event.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=max(self.interval_seconds, 1) + 1)
        logger.info("control_plane.scheduler.stopped", extra={"event": "control_plane.scheduler.stopped"})

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.interval_seconds)

    def run_once(self) -> SchedulerRunRecord:
        started_at = now_iso()
        with self._state_guard:
            self.last_started_at = started_at
        try:
            maintenance = self._runner(trigger="scheduler")
            result = maintenance["result"]
            record = SchedulerRunRecord(
                run_id=f"scheduler-run:{self.run_count + 1}",
                started_at=started_at,
                finished_at=now_iso(),
                cleaned_tokens=result["cleaned_tokens"],
                cleaned_store_records=result["cleaned_store_records"],
                cleaned_lock_slots=result["cleaned_lock_slots"],
                warnings=result["warnings"],
            )
            with self._state_guard:
                self.run_count += 1
                self.last_finished_at = record.finished_at
                self.last_run = record
                self.last_failure = ""
            logger.info(
                "control_plane.scheduler.run",
                extra={
                    "event": "control_plane.scheduler.run",
                    "run_id": record.run_id,
                    "cleaned_tokens": record.cleaned_tokens,
                    "cleaned_lock_slots": record.cleaned_lock_slots,
                    "warnings": record.warnings,
                },
            )
            return record
        except Exception as exc:
            with self._state_guard:
                self.last_failure = str(exc)
                self.last_finished_at = now_iso()
            emit_operational_signal(
                source="scheduler",
                severity="critical",
                code="scheduler_run_failed",
                detail=str(exc),
            )
            logger.exception(
                "control_plane.scheduler.failed",
                extra={"event": "control_plane.scheduler.failed", "error": str(exc)},
            )
            raise

    def status(self) -> dict[str, object]:
        with self._state_guard:
            return {
                "running": self.is_running(),
                "host_mode": self.last_host_mode,
                "interval_seconds": self.interval_seconds,
                "started_at": self.started_at,
                "last_started_at": self.last_started_at,
                "last_finished_at": self.last_finished_at,
                "run_count": self.run_count,
                "last_failure": self.last_failure,
                "last_run": asdict(self.last_run) if self.last_run else None,
            }
