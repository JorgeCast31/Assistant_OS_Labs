"""
Runner error hierarchy — Slice 1.
"""


class RunnerError(Exception):
    """Base class for all Runner errors."""


class PreflightError(RunnerError):
    """Raised when the execution request fails basic validation."""


class WorkspacePreparationError(RunnerError):
    """Raised when workspace creation or repo copy fails."""


class PolicyViolationError(RunnerError):
    """Raised when a request violates Runner policies."""


class RunnerInternalError(RunnerError):
    """Raised for unexpected internal Runner failures."""


class ApplyError(RunnerError):
    """Raised when the ApplyEngine cannot apply a change safely."""


class TestExecutionError(RunnerError):
    """Raised when the TestEngine cannot run tests safely."""
