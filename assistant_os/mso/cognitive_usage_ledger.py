"""
CognitiveUsageLedger — process-local in-memory ledger for LLM/provider/cognition usage.

Records token and cognition usage for MSO responses by mode and seat.
This is observability only — NOT authority token tracking.

Design
------
This module is intentionally NOT:
  - tracking CapabilityToken, OperationBinding, or AuthorizedPlan
  - calling token_issuer.issue_token()
  - calling PoliceGate or RunnerAPI
  - granting or revoking execution authority
  - persisting to disk (v0: ephemeral, process-local)

This IS:
  - a safe, read-only in-memory ledger for cognitive/provider token usage
  - populated by surface_behavior.py after each MSO mode handler response
  - accessible via GET /mso/cognitive-usage/recent for observability

usage_kind values
-----------------
  "provider_call"      — successful LLM provider response with tokens
  "provider_fallback"  — failed/unavailable provider, fallback response
  "mode_interaction"   — planning/validation/orchestration (no provider call)

zero_token_interaction
----------------------
  False for provider_call and provider_fallback (provider was attempted)
  True for mode_interaction (no provider call was made)

Thread safety
-------------
The in-memory ledger (_ledger list) is protected by a threading.Lock.
All reads and writes go through the lock.

Process-local scope
-------------------
Ephemeral. Does not persist across restarts. No database or network calls.

Test isolation
--------------
Use clear_cognitive_usage_for_tests() to reset the ledger between tests.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# Module-level in-memory ledger + lock
# ---------------------------------------------------------------------------

_ledger: list["CognitiveUsageRecord"] = []
_lock: threading.Lock = threading.Lock()
_MAX_RECORDS: int = 500


# ---------------------------------------------------------------------------
# CognitiveUsageRecord
# ---------------------------------------------------------------------------


@dataclass
class CognitiveUsageRecord:
    """
    Single cognitive/provider usage event for one MSO mode handler response.

    Fields
    ------
    usage_id : str
        Auto-generated unique ID for this record.

    created_at : str
        ISO 8601 UTC timestamp of when this record was created.

    trace_id : str
        context_id from the surface_behavior request (request-level trace).

    session_id : Optional[str]
        Session ID if available, None otherwise.

    surface : str
        Surface name (e.g. "mso_direct").

    agent_seat : Optional[str]
        Agent seat selected by the UI (from mso_context.agent_seat).

    effective_agent_seat : Optional[str]
        Actual backend seat used. For v0, typically "mso" for all handlers
        unless specialized routing exists for non-mso seats.

    interaction_mode : Optional[str]
        Interaction mode from mso_context (conversational/planning/validation/orchestration).

    cognition_tier : Optional[str]
        Cognition tier from mso_context (economic/advanced).

    effective_cognition_tier : Optional[str]
        Actual tier used by the backend (may differ if tier was adjusted).

    provider_used : Optional[str]
        Provider name (e.g. "anthropic"). None for non-provider responses.

    model_used : Optional[str]
        Model name (e.g. "claude-haiku-4-5-20251001"). None for non-provider responses.

    response_source : Optional[str]
        Source tag from surface_behavior (e.g. "llm_economic", "deterministic_fallback").

    usage_kind : str
        Categorizes the usage event:
          "provider_call"     — successful LLM provider response
          "provider_fallback" — provider failed/unavailable, fallback response used
          "mode_interaction"  — planning/validation/orchestration (no provider call)

    fallback_used : bool
        True when a fallback response was served instead of a provider response.

    fallback_reason : Optional[str]
        Error or reason string when fallback_used is True.

    zero_token_interaction : bool
        True for mode_interaction records where no provider call was attempted.
        False for provider_call and provider_fallback (provider was attempted).

    tokens_in : Optional[int]
        Input tokens from provider metadata. None when not applicable.

    tokens_out : Optional[int]
        Output tokens from provider metadata. None when not applicable.

    latency_ms : Optional[int]
        Wall-clock latency in milliseconds. None when not applicable.

    prepared_action_id : Optional[str]
        Prepared action ID for planning mode records.

    queue_entry_id : Optional[str]
        Queue entry ID for planning mode records.
    """

    # Auto-generated
    usage_id: str = field(default_factory=lambda: f"cu-{uuid4()}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Trace
    trace_id: str = ""
    session_id: Optional[str] = None

    # Surface
    surface: str = ""

    # Seat
    agent_seat: Optional[str] = None
    effective_agent_seat: Optional[str] = None

    # Mode
    interaction_mode: Optional[str] = None
    cognition_tier: Optional[str] = None
    effective_cognition_tier: Optional[str] = None

    # Provider
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    response_source: Optional[str] = None

    # Usage classification
    usage_kind: str = "mode_interaction"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    zero_token_interaction: bool = True

    # Token counts
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None

    # Planning linkage
    prepared_action_id: Optional[str] = None
    queue_entry_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize for API/transport. Observability only — no authority fields."""
        return {
            "usage_id": self.usage_id,
            "created_at": self.created_at,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "surface": self.surface,
            "agent_seat": self.agent_seat,
            "effective_agent_seat": self.effective_agent_seat,
            "interaction_mode": self.interaction_mode,
            "cognition_tier": self.cognition_tier,
            "effective_cognition_tier": self.effective_cognition_tier,
            "provider_used": self.provider_used,
            "model_used": self.model_used,
            "response_source": self.response_source,
            "usage_kind": self.usage_kind,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "zero_token_interaction": self.zero_token_interaction,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "prepared_action_id": self.prepared_action_id,
            "queue_entry_id": self.queue_entry_id,
        }


# ---------------------------------------------------------------------------
# Ledger operations
# ---------------------------------------------------------------------------


def record_cognitive_usage(record: CognitiveUsageRecord) -> CognitiveUsageRecord:
    """
    Append a CognitiveUsageRecord to the in-memory ledger.

    Thread-safe. Trims oldest records if ledger exceeds _MAX_RECORDS.
    Returns the record unchanged.

    Parameters
    ----------
    record : CognitiveUsageRecord
        The usage record to store.

    Returns
    -------
    CognitiveUsageRecord
        The same record that was appended.

    Raises
    ------
    TypeError
        If record is not a CognitiveUsageRecord instance.
    """
    if not isinstance(record, CognitiveUsageRecord):
        raise TypeError(
            f"record_cognitive_usage requires CognitiveUsageRecord, "
            f"got {type(record).__name__!r}."
        )
    with _lock:
        _ledger.append(record)
        if len(_ledger) > _MAX_RECORDS:
            del _ledger[: len(_ledger) - _MAX_RECORDS]
    return record


def list_recent_cognitive_usage(limit: int = 50) -> list[dict]:
    """
    Return the most recent cognitive usage records as serialized dicts, newest-first.

    Read-only. Safe for API/surface transport.

    Parameters
    ----------
    limit : int
        Maximum number of records to return. Clamped to [1, _MAX_RECORDS].

    Returns
    -------
    list[dict]
        Serialized CognitiveUsageRecord dicts, newest-first.
        Empty list if ledger is empty.
    """
    limit = max(1, min(limit, _MAX_RECORDS))
    with _lock:
        snapshot = list(_ledger)
    snapshot.sort(key=lambda r: r.created_at, reverse=True)
    return [r.to_dict() for r in snapshot[:limit]]


def clear_cognitive_usage_for_tests() -> None:
    """
    Empty the in-memory ledger. FOR TESTS ONLY.

    Must be called in test setup/teardown to prevent state bleed between tests.
    Never call this in production code paths.
    """
    with _lock:
        _ledger.clear()
