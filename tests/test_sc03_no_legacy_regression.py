"""SC-03 — No legacy `process_chat_input` regression (TDD guard).

SC-02a neutralized the legacy ungoverned write paths and `process_chat_input`
must NOT be reintroduced as the SC-03 on-ramp. The governed preparation path
(make_orchestration_proposal -> prepare_authority -> build_confirmable ->
enqueue) must reach the queue WITHOUT routing through `chat_core.process_chat_input`.

Status when first written: GREEN expected (the prep path does not touch
chat_core). This is a regression guard, not a gap demonstration.

No product logic is implemented here. Tests only.
"""

from __future__ import annotations

import assistant_os.chat_core as chat_core
from assistant_os.surface_behavior import _build_plan_request_authority_data


REPO_URL = "https://github.com/JorgeCast31/Assistant_OS_Labs"
REPO_REVIEW_TEXT = f"Revisa este repo: {REPO_URL}"


def test_t5_preparation_path_does_not_invoke_process_chat_input(monkeypatch):
    """The SC-03 preparation/enqueue path must never call process_chat_input."""
    calls: list[tuple] = []

    def _tripwire(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(
            "SC-02a regression: SC-03 preparation invoked legacy process_chat_input"
        )

    monkeypatch.setattr(chat_core, "process_chat_input", _tripwire)

    data = _build_plan_request_authority_data(REPO_REVIEW_TEXT)

    assert calls == [], "legacy process_chat_input was called during preparation"
    # Sanity: preparation still produced a non-executing proposal.
    assert (data.get("queued_prepared_action") or {}).get("execution_allowed") is False
