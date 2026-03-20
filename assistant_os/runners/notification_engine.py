"""
NotificationEngine — Slice 4.

Emits a minimal, persistent notification that an execution has finished.

Implementation: writes a single done.json file to the execution's artifacts
directory. No external systems, no email, no webhooks.

done.json is intentionally lightweight — it is the signal that the execution
completed and carries the minimum context needed by any downstream consumer.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .runner_models import NotificationResult, RunnerExecutionResult, ValidationResult

logger = logging.getLogger(__name__)


class NotificationEngine:
    """Writes done.json to signal execution completion."""

    def notify(
        self,
        result: RunnerExecutionResult,
        validation: ValidationResult,
    ) -> NotificationResult:
        """Write done.json to the execution's artifacts directory.

        Args:
            result:     The fully-populated RunnerExecutionResult.
            validation: The ValidationResult produced by ValidationEngine.

        Returns:
            NotificationResult with the absolute path to done.json.

        Raises:
            OSError: if done.json cannot be written.
        """
        artifacts_dir = Path(result.artifacts_path)
        done_path = artifacts_dir / "done.json"

        payload = {
            "execution_id": result.execution_id,
            "final_status": validation.final_status,
            "summary": validation.validation_summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        done_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(
            "Notification written for execution %s → final_status=%s",
            result.execution_id, validation.final_status,
        )

        return NotificationResult(notification_path=str(done_path))
