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
    CanonicalRequest,
    ClassifyRequest,
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

    return intent
