"""SC-03 — No Police bypass / no runner call before confirmation (TDD guard).

Before human confirmation, the conversational on-ramp must NOT invoke any
domain runner/pipeline (CODE/FIN/WORK/HOST). Dispatch may only happen through
the governed chain AFTER confirmation. Preparation is preview-only.

Status when first written: GREEN expected (preparation never touches runners;
the queued action is review-only, non-executing). This guards the invariant.

No product logic is implemented here. Tests only.
"""

from __future__ import annotations

import assistant_os.pipelines.code_pipeline as code_pipeline
from assistant_os.surface_behavior import _build_plan_request_authority_data


REPO_URL = "https://github.com/JorgeCast31/Assistant_OS_Labs"
REPO_REVIEW_TEXT = f"Revisa este repo: {REPO_URL}"


def test_t7_no_runner_call_before_confirmation(monkeypatch):
    """No CODE pipeline execution may occur during preparation (pre-confirmation)."""
    runner_calls: list[tuple] = []

    def _tripwire(*args, **kwargs):
        runner_calls.append((args, kwargs))
        raise AssertionError(
            "bypass: CODE runner executed during preparation, before confirmation"
        )

    monkeypatch.setattr(code_pipeline, "execute", _tripwire)

    data = _build_plan_request_authority_data(REPO_REVIEW_TEXT)
    queued = data.get("queued_prepared_action") or {}

    # No runner invoked.
    assert runner_calls == [], "a domain runner was called before confirmation"

    # State proves execution is gated behind confirmation.
    assert queued.get("can_execute_now") is False
    assert queued.get("execution_allowed") is False
    assert queued.get("review_only") is True
    assert queued.get("human_confirmation_status") == "pending"
