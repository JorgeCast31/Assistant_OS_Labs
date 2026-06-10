"""SC-03 — Conversational On-Ramp to Governed Mission Flow (TDD, red-first).

These tests pin the SC-03 contract:

    SC-03 does NOT create conversational authority.
    SC-03 creates conversational *intention* translated into a *governed* mission.

A natural repo-review phrase ("Revisa este repo: <url>") must become a
non-executing, confirmation-gated CODE prepared action that:
  - is classified as domain=CODE, action=CODE_REVIEW (deterministic, NOT via LLM),
  - carries the extracted repo resource (URL/path),
  - appears in the prepared-action queue / Mission Control read surface,
  - never executes and never fabricates outcome/trace, even on provider failure.

Status when first written (origin/main 9e462c2, no product code touched):
  - T1  (detection)            -> RED   (Gap A: phrase not recognized)
  - T1b (classification+resource) -> RED (Gap B: built as ASSISTANT/PLAN_REVIEW, resource=None)
  - T2  (provider no-fabrication) -> GREEN expected (invariant already held)
  - T3  (no direct execution)  -> GREEN expected (invariant already held)
  - T4  (appears in queue as CODE) -> RED (Gap B)
  - T6  (Mission Control sees CODE+resource) -> RED (Gap B)

No product logic is implemented here. Tests only.
"""

from __future__ import annotations

import pytest

from assistant_os.mso.governed_confirmation_bridge import (
    is_governed_preparation_prompt,
)
from assistant_os.surface_behavior import _build_plan_request_authority_data
from assistant_os.mso.prepared_action_queue import (
    list_pending_confirmable_action_dicts,
)
from assistant_os.mso import mso_chat_provider


# Canonical SC-03 natural-language repo-review intent + the resource it carries.
REPO_URL = "https://github.com/JorgeCast31/Assistant_OS_Labs"
REPO_REVIEW_TEXT = f"Revisa este repo: {REPO_URL}"


def _prepare(intent_text: str) -> dict:
    """Run the real (existing) preparation/enqueue path for an intent."""
    return _build_plan_request_authority_data(intent_text)


def _queue_entries_for(url: str) -> list[dict]:
    """Pending prepared-action dicts whose user_intent references the given url."""
    return [
        e
        for e in list_pending_confirmable_action_dicts()
        if url in (e.get("user_intent") or "")
    ]


# ---------------------------------------------------------------------------
# T1 — Natural repo-review intent is recognized as governed preparation intent.
# ---------------------------------------------------------------------------
def test_t1_repo_review_intent_is_detected_as_governed_preparation():
    """Gap A: a natural repo-review phrase must enter the governed prep on-ramp.

    Expected RED on origin/main: is_governed_preparation_prompt does not yet
    recognize repo-review phrasing, so the intent never reaches preparation.
    """
    assert is_governed_preparation_prompt(REPO_REVIEW_TEXT) is True, (
        "Gap A: 'Revisa este repo: <url>' is not recognized as a governed "
        "preparation intent; it falls through to the narrative/plan_request path."
    )


# ---------------------------------------------------------------------------
# T1b — Repo-review intent creates a prepared CODE action with the resource.
# ---------------------------------------------------------------------------
def test_t1b_repo_review_intent_creates_prepared_code_action():
    """Gap B: the prepared action must be CODE / CODE_REVIEW with the repo resource.

    Expected RED on origin/main: built as ASSISTANT / PLAN_REVIEW, resource absent.
    """
    data = _prepare(REPO_REVIEW_TEXT)
    confirmable = data.get("confirmable_action") or {}

    # Never executes (invariant — should already hold).
    assert confirmable.get("execution_allowed") is False
    assert confirmable.get("cognitive_only") is True

    # Classification (Gap B).
    assert confirmable.get("domain") == "CODE", (
        f"Gap B: expected domain=CODE, got {confirmable.get('domain')!r}"
    )
    assert confirmable.get("requested_action") == "CODE_REVIEW", (
        f"Gap B: expected requested_action=CODE_REVIEW, "
        f"got {confirmable.get('requested_action')!r}"
    )

    # Resource extraction (Gap B): the repo URL must be captured deterministically.
    assert confirmable.get("resource") == REPO_URL, (
        f"Gap B: expected resource={REPO_URL!r}, got {confirmable.get('resource')!r} "
        "(no resource field is produced today)."
    )


# ---------------------------------------------------------------------------
# T2 — Provider failure does not fabricate outcome/trace/execution claim.
# ---------------------------------------------------------------------------
def test_t2_provider_failure_does_not_fabricate(monkeypatch):
    """Forced cognitive-provider failure must stay honest: no fabricated result.

    Expected GREEN: mso_chat_provider already returns an 'unavailable' response
    with used_execution=False and no outcome/trace. This locks that invariant.
    (The separate 'still offer to prepare the mission' behavior depends on Gap A
    and is covered by T1 / T1b.)
    """
    def _boom():
        raise RuntimeError("forced provider failure for SC-03 T2")

    monkeypatch.setattr(mso_chat_provider, "is_mso_chat_available", lambda: True)
    monkeypatch.setattr(mso_chat_provider, "_get_anthropic_client", _boom)

    resp = mso_chat_provider.call_mso_chat_provider(
        grounding_context={}, user_text=REPO_REVIEW_TEXT
    )

    assert resp.get("status") in {"unavailable", "error"}
    assert resp.get("used_execution") is False
    assert resp.get("cognitive_only") is True
    # No fabricated execution evidence.
    assert "outcome" not in resp
    assert "trace" not in resp
    text = (resp.get("text") or "").lower()
    for claim in ("executed", "ejecutado", "completed successfully", "done"):
        assert claim not in text, f"fabricated execution claim in provider text: {claim!r}"


# ---------------------------------------------------------------------------
# T3 — Chat preparation can never execute directly.
# ---------------------------------------------------------------------------
def test_t3_chat_preparation_never_executes_directly():
    """Preparing from chat must yield a non-executing, confirmation-gated action.

    Expected GREEN: the prepared/queued action already carries the fail-closed
    invariants. This guards against any future regression toward direct execution.
    """
    data = _prepare(REPO_REVIEW_TEXT)
    queued = data.get("queued_prepared_action") or {}

    assert data.get("execution_allowed") is False
    assert queued.get("execution_allowed") is False
    assert queued.get("can_execute_now") is False
    assert queued.get("review_only") is True
    assert queued.get("human_confirmation_status") == "pending"
    assert queued.get("status") == "pending_review"


# ---------------------------------------------------------------------------
# T4 — The prepared CODE action appears in the queue.
# ---------------------------------------------------------------------------
def test_t4_prepared_code_action_appears_in_queue():
    """The prepared action must surface in the pending queue as a CODE action.

    Expected RED on origin/main: an entry appears, but as ASSISTANT (Gap B),
    so no CODE entry is found.
    """
    _prepare(REPO_REVIEW_TEXT)
    entries = _queue_entries_for(REPO_URL)
    assert entries, "no prepared action was enqueued for the repo-review intent"
    code_entries = [e for e in entries if e.get("domain") == "CODE"]
    assert code_entries, (
        "Gap B: prepared action is queued but not as domain=CODE "
        f"(domains seen: {sorted({e.get('domain') for e in entries})})."
    )


# ---------------------------------------------------------------------------
# T6 — Mission Control read surface exposes the CODE action + resource.
# ---------------------------------------------------------------------------
def test_t6_mission_control_dicts_expose_code_action_and_resource():
    """list_pending_confirmable_action_dicts() must expose domain=CODE + resource.

    Expected RED on origin/main: no resource field, domain is ASSISTANT (Gap B).
    """
    _prepare(REPO_REVIEW_TEXT)
    entries = _queue_entries_for(REPO_URL)
    assert entries, "Mission Control surface returned no entry for the intent"
    match = [
        e
        for e in entries
        if e.get("domain") == "CODE" and e.get("resource") == REPO_URL
    ]
    assert match, (
        "Gap B: Mission Control cannot retrieve a CODE prepared action carrying "
        f"resource={REPO_URL!r} (resource field is not produced today)."
    )
