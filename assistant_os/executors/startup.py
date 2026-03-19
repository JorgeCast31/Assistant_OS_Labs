"""
Executor startup wiring for Assistant OS.

Provides:
  setup_code_read_executor()    — wire real Claude executor for CODE_EXPLAIN/REVIEW
  setup_code_propose_executor() — wire real Claude executor for CODE_FIX/CREATE preview
  setup_all_code_executors()    — convenience: sets up both in one call
  get_code_executor_status()    — read current review executor status (no side effects)
  get_propose_executor_status() — read current propose executor status (no side effects)

Design
------
- Called at server startup (run_server) and CLI entry (main).
- Safe to call multiple times — idempotent.  register_*_executor simply
  overwrites the module-level variable; no resource is leaked on double-call.
- Never raises.  Any error during executor construction falls back to stub and
  returns a status dict explaining why.

Return value (all setup functions)
------------------------------------
{
    "live":  bool        — True if real executor was registered
    "model": str | None  — Model ID when live, None when stub
    "note":  str         — Human-readable status detail (empty string on success)
}
"""

from __future__ import annotations


def setup_code_read_executor() -> dict:
    """
    Wire the real Claude executor for CODE_EXPLAIN / CODE_REVIEW.

    Behaviour
    ---------
    - ANTHROPIC_API_KEY present  → build real executor, register it, return live=True
    - ANTHROPIC_API_KEY absent   → ensure stub is active, return live=False
    - Any exception during build → fall back to stub, return live=False with note

    This function is idempotent: calling it twice has the same effect as calling
    it once.

    Returns
    -------
    dict with keys: live (bool), model (str | None), note (str)
    """
    from ..config import ANTHROPIC_API_KEY, CODE_REVIEW_MODEL
    from ..pipelines.code_pipeline import register_review_executor

    if not ANTHROPIC_API_KEY:
        # Keep (or reset to) stub — no crash, just a note
        register_review_executor(None)
        return {
            "live": False,
            "model": None,
            "note": "ANTHROPIC_API_KEY not configured — using stub executor",
        }

    try:
        from .code_review_executor import build_claude_review_executor
        executor = build_claude_review_executor()
        register_review_executor(executor)
        return {
            "live": True,
            "model": CODE_REVIEW_MODEL,
            "note": "",
        }
    except Exception as exc:
        # Construction failed (e.g. import error, bad config) — fall back safely
        register_review_executor(None)
        return {
            "live": False,
            "model": None,
            "note": f"executor setup failed: {exc}",
        }


def get_code_executor_status() -> dict:
    """
    Return the current CODE read-only executor status without changing anything.

    Used by the startup banner to report current state.

    Returns
    -------
    dict with keys: live (bool), model (str | None)
    """
    from ..pipelines.code_pipeline import _review_executor
    from ..config import CODE_REVIEW_MODEL

    live = _review_executor is not None
    return {
        "live": live,
        "model": CODE_REVIEW_MODEL if live else None,
    }


def setup_code_propose_executor() -> dict:
    """
    Wire the real Claude executor for CODE_FIX / CODE_CREATE preview generation.

    The apply path is always stubbed — this function has zero effect on apply.

    Behaviour
    ---------
    - ANTHROPIC_API_KEY present  → build real executor, register it, return live=True
    - ANTHROPIC_API_KEY absent   → ensure stub is active, return live=False
    - Any exception during build → fall back to stub, return live=False with note

    This function is idempotent.

    Returns
    -------
    dict with keys: live (bool), model (str | None), note (str)
    """
    from ..config import ANTHROPIC_API_KEY, CODE_PROPOSE_MODEL
    from ..pipelines.code_pipeline import register_propose_executor

    if not ANTHROPIC_API_KEY:
        register_propose_executor(None)
        return {
            "live": False,
            "model": None,
            "note": "ANTHROPIC_API_KEY not configured — using stub executor",
        }

    try:
        from .code_propose_executor import build_claude_propose_executor
        executor = build_claude_propose_executor()
        register_propose_executor(executor)
        return {
            "live": True,
            "model": CODE_PROPOSE_MODEL,
            "note": "",
        }
    except Exception as exc:
        register_propose_executor(None)
        return {
            "live": False,
            "model": None,
            "note": f"executor setup failed: {exc}",
        }


def get_propose_executor_status() -> dict:
    """
    Return the current CODE propose executor status without changing anything.

    Returns
    -------
    dict with keys: live (bool), model (str | None)
    """
    from ..pipelines.code_pipeline import _propose_executor
    from ..config import CODE_PROPOSE_MODEL

    live = _propose_executor is not None
    return {
        "live": live,
        "model": CODE_PROPOSE_MODEL if live else None,
    }


def setup_all_code_executors() -> dict:
    """
    Convenience: set up both CODE executors in one call.

    Returns
    -------
    dict with keys:
        review  : dict — result of setup_code_read_executor()
        propose : dict — result of setup_code_propose_executor()
    """
    return {
        "review": setup_code_read_executor(),
        "propose": setup_code_propose_executor(),
    }
