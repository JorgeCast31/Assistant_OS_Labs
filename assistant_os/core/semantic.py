"""
Kernel — Semantic Layer

Responsibility: transform a CanonicalRequest into an intent dict that
describes what the user wants at the semantic level.

Also applies HTTP-layer routing hints (forced_operation) so the rest of
the kernel sees a consistent intent regardless of origin.

classify_text is lazy-imported from classifier (its real owner) so that
test patches applied to assistant_os.classifier.classify_text remain
effective.  The function is re-exported by webhook_server as a
compatibility alias, but the kernel must not depend on the HTTP layer.
"""

from __future__ import annotations

from ..contracts import (
    ACTION_CODE_EXPLAIN,
    ACTION_CODE_REVIEW,
    ACTION_COMMAND,
    ACTION_FIN_EXPENSE,
    ACTION_WORK_CREATE,
    ACTION_WORK_QUERY,
    CanonicalRequest,
    ClassifyRequest,
    OP_CODE_EXPLAIN,
    OP_CODE_REVIEW,
    OP_WORK_QUERY,
    OP_WORK_CREATE,
    OP_WORK_UPDATE,
    OP_WORK_DELETE,
    OP_FIN_EXPENSE,
)

_VALID_OPERATIONS = (
    OP_WORK_QUERY,
    OP_WORK_CREATE,
    OP_WORK_UPDATE,
    OP_WORK_DELETE,
    OP_FIN_EXPENSE,
)

_ROUTING_CONTEXT_ACTION_TO_OPERATION = {
    ("CODE", ACTION_CODE_EXPLAIN): OP_CODE_EXPLAIN,
    ("CODE", ACTION_CODE_REVIEW): OP_CODE_REVIEW,
    ("FIN", ACTION_FIN_EXPENSE): OP_FIN_EXPENSE,
    ("WORK", ACTION_WORK_CREATE): OP_WORK_CREATE,
    ("WORK", ACTION_WORK_QUERY): OP_WORK_QUERY,
}


def _validated_routing_context_operation(req: CanonicalRequest) -> tuple[str, str, float]:
    """Return a safe operation hint from assistant_chat routing_context.

    The hint is advisory only: classifier always runs first, and only known
    domain/action pairs that planner already understands can influence the
    semantic intent. Malformed, authoritative, or command-like hints are ignored.
    """
    metadata = req.get("metadata")
    if not isinstance(metadata, dict):
        return "", "", 0.0
    if metadata.get("surface") != "assistant_chat":
        return "", "", 0.0

    routing_context = metadata.get("routing_context")
    if not isinstance(routing_context, dict):
        return "", "", 0.0

    if routing_context.get("authoritative") is not False:
        return "", "", 0.0
    if routing_context.get("intent_type") != "executable_intent":
        return "", "", 0.0
    if (
        "should_pass_to_kernel" in routing_context
        and routing_context.get("should_pass_to_kernel") is not True
    ):
        return "", "", 0.0

    try:
        confidence = float(routing_context.get("confidence", 0.0))
    except (TypeError, ValueError):
        return "", "", 0.0
    if confidence < 0.70:
        return "", "", 0.0

    domain = str(routing_context.get("domain") or "").upper()
    action = str(routing_context.get("action") or "").upper()
    if action == ACTION_COMMAND or action.endswith("_COMMAND"):
        return "", "", 0.0

    operation = _ROUTING_CONTEXT_ACTION_TO_OPERATION.get((domain, action), "")
    if not operation:
        return "", "", 0.0

    return domain, operation, confidence


def classify(req: CanonicalRequest, forced_operation: str = "") -> dict:
    """
    Classify a CanonicalRequest and return an intent dict.

    Args:
        req:               Normalized CanonicalRequest.
        forced_operation:  Optional operation override from the HTTP routing
                           layer. When valid, it replaces the classifier's
                           inferred operation.

    Returns:
        intent dict — keys: operation, confidence, reason, and classifier
        metadata. Mutated in-place if forced_operation is provided.
    """
    from ..classifier import classify_text

    text = req["text"]
    classify_request: ClassifyRequest = {"text": text}
    intent: dict = classify_text(classify_request)

    if forced_operation and forced_operation in _VALID_OPERATIONS:
        intent["operation"] = forced_operation
        intent["reason"] = f"forced:{forced_operation}," + intent.get("reason", "")

    hint_domain, hint_operation, hint_confidence = _validated_routing_context_operation(req)
    if hint_operation:
        intent["domain"] = hint_domain
        intent["operation"] = hint_operation
        intent["confidence"] = max(float(intent.get("confidence", 0.0)), hint_confidence)
        intent["routing_context_used"] = True
        intent["reason"] = (
            f"routing_context:{hint_operation},"
            + intent.get("reason", "")
        )

    return intent
