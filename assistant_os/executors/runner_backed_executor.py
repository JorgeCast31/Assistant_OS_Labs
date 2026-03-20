"""
RunnerBackedExecutor — Slice 1.

Thin adapter that delegates execution to RunnerService.
No additional logic — exists solely to satisfy the Executor contract.

Integration status (pre-Slice 4):
    This class is NOT yet wired into the CODE pipeline. It exists as the
    intended integration point between the CODE closure agent and the Runner.

    TODO (Slice 4): locate the CODE pipeline's executor dispatch logic and
    replace the current executor with RunnerBackedExecutor, passing a
    RunnerExecutionRequest built from the agent's plan context.
    The executor contract is: execute(request) → RunnerExecutionResult.
"""

from __future__ import annotations

from ..runners.runner_models import RunnerExecutionRequest, RunnerExecutionResult
from ..runners.runner_service import RunnerService


class RunnerBackedExecutor:
    """Executor that backs its execution against the Runner pipeline."""

    def __init__(self) -> None:
        self._service = RunnerService()

    def execute(self, request: RunnerExecutionRequest) -> RunnerExecutionResult:
        """Delegate *request* to RunnerService and return its result."""
        return self._service.run(request)
