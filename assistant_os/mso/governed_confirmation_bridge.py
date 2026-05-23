"""MSO Governed Confirmation Bridge — S-MSO-DIRECT-GOVERNED-CONFIRMATION-BRIDGE-01.

Bridges a natural-language governed preparation intent into a structured,
deterministic response that guides the operator toward the governed execution path.

This module is intentionally NOT:
  - executing anything
  - calling the Runner or any pipeline
  - calling Police
  - issuing CapabilityToken or AuthorizedPlan
  - fabricating action IDs or authority refs
  - creating side effects

This IS:
  - a pure read model / proposal builder
  - producing a structured bridge response from intent metadata + optional prepared action
  - reporting the full required authority chain
  - declaring next safe action honestly
  - returning execution_allowed=False, can_execute_now=False, used_execution=False always

Invariants (enforced by build_governed_confirmation_bridge)
-----------------------------------------------------------
  used_execution    = False  (always)
  can_execute_now   = False  (always)
  execution_allowed = False  (always)

Detection
---------
is_governed_preparation_prompt(text) returns True for natural-language inputs
that express governed preparation intent (English and Spanish). Phrases not in
the bridge vocabulary are routed by the existing plan_request / narrative paths.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------------------
# Bridge version
# ---------------------------------------------------------------------------

BRIDGE_VERSION = "1"
BRIDGE_TYPE = "mso_direct_to_governed_confirmation"
BRIDGE_ENTITY = "MSO"

# ---------------------------------------------------------------------------
# Required authority chain (canonical order)
# ---------------------------------------------------------------------------

REQUIRED_AUTHORITY_CHAIN: tuple[str, ...] = (
    "MSO Kernel",
    "Policy",
    "Governance",
    "CapabilityToken",
    "Police",
    "AuthorityArtifact",
    "Runner",
)

# ---------------------------------------------------------------------------
# Governed preparation prompt detection
# ---------------------------------------------------------------------------

# Phrases that signal the user wants to enter the governed preparation bridge.
# These are ADDITIVE to the existing plan_request router patterns.
# They focus on "confirmable action" / "governed action" framing that the
# existing router does not specifically classify.
_GOVERNED_BRIDGE_RE = re.compile(
    r"(?:"
    # English — confirmable / governed framing
    r"\bturn this into a confirmable action\b"
    r"|\bprepare this action\b"
    r"|\bprepare governed action\b"
    r"|\bplan this for execution\b"
    r"|\bvalidate this before execution\b"
    r"|\bvalidate before executing\b"
    r"|\bcan this be executed safely\b"
    r"|\bmso[,.]?\s*prepare\b"
    r"|\bmso[,.]?\s*plan this\b"
    r"|\bwhat is the next safe step\b"
    r"|\bwhat.s the next safe step\b"
    r"|\bguided execution\b"
    r"|\bconfirmable action\b"
    # Spanish — governed / confirmable framing
    r"|\bconvertir en accion confirmable\b"
    r"|\bprepara esta accion\b"
    r"|\bprepara esto para ejecucion\b"
    r"|\bpreparar para ejecucion\b"
    r"|\baccion confirmable\b"
    r"|\bvalidar antes de ejecutar\b"
    r"|\borquestar con confirmacion\b"
    r"|\bprepara accion gobernada\b"
    r"|\bcual es el proximo paso seguro\b"
    r"|\bproximo paso seguro\b"
    r"|\borquestar con gobernanza\b"
    r")",
    re.IGNORECASE,
)


def _normalize_for_detection(text: str) -> str:
    """Normalize text for phrase matching: lowercase, strip accents, strip punctuation."""
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return ascii_text.strip("?!.,;:\xa1\xbf").strip()


def is_governed_preparation_prompt(text: str) -> bool:
    """Return True if text expresses a governed preparation / confirmable action intent.

    Pure detection — no side effects, no I/O, no network.

    Parameters
    ----------
    text:
        Raw or normalized user input.

    Returns
    -------
    bool
        True if the text matches a governed preparation bridge phrase.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = _normalize_for_detection(text)
    return bool(_GOVERNED_BRIDGE_RE.search(normalized))


# ---------------------------------------------------------------------------
# Bridge response builder
# ---------------------------------------------------------------------------

_NEXT_SAFE_ACTION_DEFAULT = (
    "Review this proposal and confirm through the governed flow: "
    "enqueue → human confirmation → policy review → authority binding → "
    "CapabilityToken → Police → Runner."
)

_AUTHORITY_PATH_DEFAULT: dict[str, Any] = {
    "required_chain": list(REQUIRED_AUTHORITY_CHAIN),
    "current_stage": "proposal",
    "next_required_stage": "human_confirmation",
    "chain_note": (
        "Full authority chain required before any execution: "
        "MSO Kernel → Policy → Governance → CapabilityToken → Police → AuthorityArtifact → Runner."
    ),
}


def build_governed_confirmation_bridge(
    *,
    text: str,
    intent_metadata: dict | None = None,
    mso_context: dict | None = None,
    prepared_action_data: dict | None = None,
) -> dict:
    """Build a governed confirmation bridge response.

    Pure function — no side effects, no I/O, no network, no token issuance,
    no Police call, no Runner call. Does not fabricate action IDs.

    Parameters
    ----------
    text:
        The original user text (used for proposal summary and intent extraction).
    intent_metadata:
        Optional normalized intent metadata dict (from normalize_mso_intent_metadata).
        If None, defaults are used.
    mso_context:
        Optional mso_context dict from the surface request. Used for traceability only.
    prepared_action_data:
        Optional dict from _build_plan_request_authority_data() if a prepared action
        was created by the caller. If None, prepared_action.created=False is reported.
        If provided, the queue_entry_id and action_id are included.

    Returns
    -------
    dict
        Structured bridge response. Always: used_execution=False, can_execute_now=False,
        execution_allowed=False. Does not raise.
    """
    try:
        return _build_bridge(
            text=text,
            intent_metadata=intent_metadata,
            mso_context=mso_context,
            prepared_action_data=prepared_action_data,
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft, bridge must never raise
        return {
            "bridge_version": BRIDGE_VERSION,
            "entity": BRIDGE_ENTITY,
            "bridge_type": BRIDGE_TYPE,
            "status": "needs_more_context",
            "used_execution": False,
            "can_execute_now": False,
            "execution_allowed": False,
            "intent_metadata": intent_metadata or {},
            "proposal": {
                "summary": str(text)[:200] if text else "",
                "requested_action": "",
                "risk_note": "Bridge construction failed; proposal could not be built.",
                "requires_confirmation": True,
            },
            "authority_path": _AUTHORITY_PATH_DEFAULT,
            "prepared_action": {
                "created": False,
                "id": None,
                "reason": f"bridge_construction_error: {exc!s}"[:200],
            },
            "next_safe_action": _NEXT_SAFE_ACTION_DEFAULT,
            "_error": str(exc)[:200],
        }


def _build_bridge(
    *,
    text: str,
    intent_metadata: dict | None,
    mso_context: dict | None,
    prepared_action_data: dict | None,
) -> dict:
    """Internal bridge builder — not for direct external call."""
    # -- Normalize intent metadata -------------------------------------------
    from .intent_contract import normalize_mso_intent_metadata, INTENT_MODE_PLANNING
    norm_intent = normalize_mso_intent_metadata(intent_metadata)
    # Bridge always targets planning intent
    norm_intent = {**norm_intent, "intent_mode": INTENT_MODE_PLANNING, "execution_intent": False}

    # -- Derive proposal summary from text -----------------------------------
    safe_text = (text or "").strip()
    summary = safe_text[:300] if safe_text else "(no intent text provided)"

    # -- Determine prepared action status ------------------------------------
    pa_created = False
    pa_id: str | None = None
    pa_reason = "read_model_only"

    if prepared_action_data and isinstance(prepared_action_data, dict):
        queued = prepared_action_data.get("queued_prepared_action") or {}
        entry_id = queued.get("queue_entry_id") or None
        action_id = queued.get("prepared_action_id") or None
        if entry_id:
            pa_created = True
            pa_id = entry_id
            pa_reason = "creation_supported"
        else:
            pa_reason = "needs_more_context"

    # -- Determine bridge status ---------------------------------------------
    if pa_created:
        status = "prepared_action_created"
    elif safe_text:
        status = "proposal_ready"
    else:
        status = "needs_more_context"

    # -- Build proposal summary ----------------------------------------------
    proposal = {
        "summary": summary,
        "requested_action": _infer_requested_action(safe_text),
        "risk_note": (
            "All execution requires full authority chain: "
            "MSO Kernel → Policy → Governance → CapabilityToken → Police → AuthorityArtifact → Runner. "
            "No execution has occurred. This is a proposal only."
        ),
        "requires_confirmation": True,
    }

    # -- Build authority path ------------------------------------------------
    authority_path: dict[str, Any] = {
        "required_chain": list(REQUIRED_AUTHORITY_CHAIN),
        "current_stage": "proposal",
        "next_required_stage": "human_confirmation",
        "chain_note": (
            "Full authority chain required before any execution. "
            "Current stage: proposal (no authority satisfied). "
            "Next required: human_confirmation via governed flow."
        ),
    }

    # -- Build prepared_action block -----------------------------------------
    prepared_action: dict[str, Any] = {
        "created": pa_created,
        "id": pa_id,
        "reason": pa_reason,
    }

    # -- Next safe action ----------------------------------------------------
    if pa_created and pa_id:
        next_safe_action = (
            f"A prepared action has been queued (queue_entry_id={pa_id!r}). "
            "Review it in Mission Control and confirm via the human confirmation step."
        )
    elif safe_text:
        next_safe_action = _NEXT_SAFE_ACTION_DEFAULT
    else:
        next_safe_action = (
            "Provide the intent text you want to govern, then request preparation again."
        )

    return {
        "bridge_version": BRIDGE_VERSION,
        "entity": BRIDGE_ENTITY,
        "bridge_type": BRIDGE_TYPE,
        "status": status,
        "used_execution": False,
        "can_execute_now": False,
        "execution_allowed": False,
        "intent_metadata": norm_intent,
        "proposal": proposal,
        "authority_path": authority_path,
        "prepared_action": prepared_action,
        "next_safe_action": next_safe_action,
    }


def _infer_requested_action(text: str) -> str:
    """Derive a short requested_action label from the user text.

    Extracts the first clause without fabricating meaning.
    Caps at 120 characters. Returns empty string if text is empty.
    """
    if not text:
        return ""
    first_clause = text.split(".")[0].split("\n")[0].strip()
    return first_clause[:120] if first_clause else text[:120]
