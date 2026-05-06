"""Deterministic translation from SovereignIntent to CanonicalRequest."""

from __future__ import annotations

from dataclasses import asdict
import uuid

from ..contracts import ACTION_BASIC_COGNITIVE_EXECUTION, CanonicalRequest, normalize_request, now_iso
from .contracts import DelegationTask, SovereignIntent, TranslatorRejection
from .delegation import validate_delegation_task, validate_sovereign_intent

_ALLOWED_DELEGATION_RECOMMENDATIONS = frozenset({"none", "delegate_basic_cognitive_execution"})

_MSO_PRINCIPAL_ID = "mso:sovereign"
_MSO_SUBJECT_STATE = "active"


class TranslatorValidationError(ValueError):
    """Explicit deterministic translator rejection."""

    def __init__(self, rejection: TranslatorRejection):
        super().__init__(rejection.message)
        self.rejection = rejection


def _reject(
    intent: SovereignIntent,
    *,
    original_text: str,
    reason_code: str,
    message: str,
) -> None:
    raise TranslatorValidationError(
        TranslatorRejection(
            rejection_id=str(uuid.uuid4()),
            intent_id=intent.intent_id,
            session_id=intent.session_id,
            trace_id=f"translator:{intent.intent_id}",
            reason_code=reason_code,
            message=message,
            original_text=original_text,
            created_at=now_iso(),
        )
    )


def _validate_translation_inputs(
    intent: SovereignIntent,
    *,
    original_text: str,
    delegation_task: DelegationTask | None,
) -> None:
    validate_sovereign_intent(intent)
    if not original_text.strip():
        _reject(
            intent,
            original_text=original_text,
            reason_code="empty_original_text",
            message="Translator requires a non-empty original user request.",
        )
    if not intent.interpreted_goal.strip():
        _reject(
            intent,
            original_text=original_text,
            reason_code="empty_interpreted_goal",
            message="Translator requires an interpreted goal before mapping.",
        )
    if intent.delegation_recommendation not in _ALLOWED_DELEGATION_RECOMMENDATIONS:
        _reject(
            intent,
            original_text=original_text,
            reason_code="unsupported_delegation_recommendation",
            message=f"Unsupported delegation recommendation: {intent.delegation_recommendation!r}.",
        )
    if intent.delegation_recommendation == "none" and delegation_task is not None:
        _reject(
            intent,
            original_text=original_text,
            reason_code="unexpected_delegation_task",
            message="Translator refuses a delegation task when delegation recommendation is 'none'.",
        )
    if intent.delegation_recommendation == "delegate_basic_cognitive_execution":
        if delegation_task is None:
            _reject(
                intent,
                original_text=original_text,
                reason_code="missing_delegation_task",
                message="DelegationTask is required for delegated sovereign intent translation.",
            )
        validate_delegation_task(delegation_task)
        if delegation_task.origin_intent_id != intent.intent_id:
            _reject(
                intent,
                original_text=original_text,
                reason_code="delegation_intent_mismatch",
                message="DelegationTask origin_intent_id must match the SovereignIntent intent_id.",
            )


def _apply_mso_identity_context(req: CanonicalRequest, *, action_type: str) -> CanonicalRequest:
    """Attach identity context only for policy input shaping, never authority."""
    req["principal_id"] = _MSO_PRINCIPAL_ID
    req["subject_state"] = _MSO_SUBJECT_STATE
    req["action_type"] = action_type
    return req


def _translate_delegated_intent(
    intent: SovereignIntent,
    *,
    original_text: str,
    context_id: str,
    delegation_task: DelegationTask,
) -> CanonicalRequest:
    req = normalize_request(
        text=original_text,
        context_id=context_id or intent.session_id,
        metadata={
            "action": ACTION_BASIC_COGNITIVE_EXECUTION,
            "domain": "COGNITIVE",
            "target": intent.interpreted_goal,
            "risk_level": "low",
            "requires_confirmation": False,
            "mso_intent_ref": intent.intent_id,
            "translation_rule": "delegate_basic_cognitive_execution",
            "domain_payload": {
                "sovereign_intent": asdict(intent),
                "delegation_task": asdict(delegation_task),
            },
        },
    )
    return _apply_mso_identity_context(req, action_type="execute")


def _translate_response_intent(
    intent: SovereignIntent,
    *,
    original_text: str,
    context_id: str,
) -> CanonicalRequest:
    req = normalize_request(
        text=original_text,
        context_id=context_id or intent.session_id,
        metadata={
            "mso_intent_ref": intent.intent_id,
            "translation_rule": "respond_passthrough",
        },
    )
    return _apply_mso_identity_context(req, action_type="read")


def translate_intent_to_canonical_request(
    intent: SovereignIntent,
    *,
    original_text: str,
    context_id: str = "",
    delegation_task: DelegationTask | None = None,
) -> CanonicalRequest:
    """Translate sovereign intent into canonical request input without granting authority."""
    _validate_translation_inputs(intent, original_text=original_text, delegation_task=delegation_task)
    if intent.delegation_recommendation == "delegate_basic_cognitive_execution":
        assert delegation_task is not None  # validated above
        return _translate_delegated_intent(
            intent,
            original_text=original_text,
            context_id=context_id,
            delegation_task=delegation_task,
        )
    return _translate_response_intent(intent, original_text=original_text, context_id=context_id)
