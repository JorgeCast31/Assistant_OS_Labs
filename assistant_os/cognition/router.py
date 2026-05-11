"""Deterministic Cognitive Router v0.

This module is advisory-only. It does not call LLMs, mutate registries,
create confirmations, grant capabilities, or execute actions.
"""
from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Literal, TypedDict


RouterIntentType = Literal[
    "conversational",
    "capability_summary",
    "read_only_status",
    "review_queue_status",
    "needs_context",
    "executable_intent",
    "plan_request",
    "unknown_ambiguous",
]


class RouterResult(TypedDict):
    intent_type: str
    domain: str
    action: str
    confidence: float
    missing_fields: list[str]
    entities: dict[str, Any]
    should_pass_to_kernel: bool
    routing_reason: str
    safety_flags: list[str]
    router_version: str
    advisory_used: bool
    advisory_latency_ms: float


ROUTER_VERSION = "v0_deterministic"
ALLOWED_INTENT_TYPES: frozenset[str] = frozenset(
    {
        "conversational",
        "capability_summary",
        "read_only_status",
        "review_queue_status",
        "needs_context",
        "executable_intent",
        "plan_request",
        "unknown_ambiguous",
    }
)
EXECUTABLE_DOMAINS: frozenset[str] = frozenset({"WORK", "FIN", "CODE", "HOST"})
SAFETY_FLAG_VOCABULARY: frozenset[str] = frozenset(
    {
        "social_engineering",
        "prompt_injection",
        "destructive_request",
        "unsafe_host_request",
        "unknown_intent",
    }
)

_GITHUB_URL_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?<!\w)(?:\.\/|\.\.\/|[a-z]:[\\/]|/)[^\s]+", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

# RC-1: capability_summary — Spanish + English paraphrases (full-string match)
_CAPABILITY_RE = re.compile(
    r"^(?:"
    r"que puedes hacer(?: tu)?"
    r"|dime(?:\s+lo)?\s+que\s+puedes\s+hacer"
    r"|dime\s+tus\s+capacidades"
    r"|cuales\s+son\s+tus\s+capacidades"
    r"|que\s+capacidades\s+(?:tienes|hay)"
    r"|capacidades?"
    r"|what\s+can\s+you\s+do"
    r"|what\s+are\s+your\s+capabilities"
    r"|capabilit(?:y|ies)"
    r")$"
)

# RC-4: review_queue_status — manual review queue status queries (substring match)
_REVIEW_QUEUE_RE = re.compile(
    r"(?:"
    r"\bwaiting\s+for\s+manual\s+review\b"
    r"|\bwhat\s+is\s+waiting\b"
    r"|\bshow\s+pending\s+(?:prepared\s+)?actions?\b"
    r"|\bpending\s+prepared\s+actions?\b"
    r"|\bwhat\s+(?:actions?\s+(?:are|is)\s+)?queued\b"
    r"|\bwhat\s+did\s+you\s+prepare\b"
    r"|\bwhat\s+authority\s+is\s+(?:still\s+)?pending\b"
    r"|\bwhat\s+can\s+code\s+do\s+next\b"
    r"|\breview\s+queue\b"
    r"|\bqueue\s+status\b"
    r"|\bque\s+esta\s+esperando\b"
    r"|\bque\s+acciones\s+estan\s+en\s+cola\b"
    r"|\bmuestra\s+(?:las\s+)?acciones?\s+pendientes?\b"
    r"|\bque\s+preparaste\b"
    r"|\bacciones?\s+en\s+cola\b"
    r"|\bacciones?\s+pendientes?\s+de\s+revision\b"
    r"|\bpendiente(?:s)?\s+de\s+revision\s+manual\b"
    r")"
)

# RC-3: plan_request — plan-only / dry-run phrases (substring match)
_PLAN_REQUEST_RE = re.compile(
    r"(?:"
    r"\bprepare a plan\b"
    r"|\bplan only\b"
    r"|\bdry[ -]run\b"
    r"|\bdo not execute\b"
    r"|\bplan for\b"
    r"|\bprepara un plan\b"
    r"|\bplanifica\b"
    r"|\bsin ejecutar\b"
    r"|\bno ejecutes\b"
    r"|\bsolo plan\b"
    r"|\bmodo plan\b"
    r")"
)


def _normalize(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    stripped = ascii_text.strip("?!.,;:\xa1\xbf").strip()
    cleaned = []
    for ch in stripped:
        cleaned.append(" " if ch in "?!\xa1\xbf" else ch)
    return " ".join("".join(cleaned).split())


def _base_result(
    *,
    intent_type: str,
    domain: str,
    action: str,
    confidence: float,
    missing_fields: list[str] | None = None,
    entities: dict[str, Any] | None = None,
    should_pass_to_kernel: bool = False,
    routing_reason: str,
    safety_flags: list[str] | None = None,
    advisory_latency_ms: float = 0.0,
) -> RouterResult:
    return {
        "intent_type": intent_type,
        "domain": domain,
        "action": action,
        "confidence": float(confidence),
        "missing_fields": list(missing_fields or []),
        "entities": dict(entities or {}),
        "should_pass_to_kernel": bool(should_pass_to_kernel),
        "routing_reason": routing_reason,
        "safety_flags": list(safety_flags or []),
        "router_version": ROUTER_VERSION,
        "advisory_used": False,
        "advisory_latency_ms": float(advisory_latency_ms),
    }


def _unknown(
    *,
    routing_reason: str,
    safety_flags: list[str] | None = None,
    advisory_latency_ms: float = 0.0,
) -> RouterResult:
    return _base_result(
        intent_type="unknown_ambiguous",
        domain="UNKNOWN",
        action="",
        confidence=0.30,
        routing_reason=routing_reason,
        safety_flags=safety_flags,
        advisory_latency_ms=advisory_latency_ms,
    )


def validate_router_result(raw: dict[str, Any]) -> RouterResult:
    """Return a fail-closed RouterResult that satisfies v0 invariants."""
    result = _base_result(
        intent_type=str(raw.get("intent_type") or "unknown_ambiguous"),
        domain=str(raw.get("domain") or "UNKNOWN").upper(),
        action=str(raw.get("action") or ""),
        confidence=_coerce_confidence(raw.get("confidence")),
        missing_fields=_coerce_str_list(raw.get("missing_fields")),
        entities=raw.get("entities") if isinstance(raw.get("entities"), dict) else {},
        should_pass_to_kernel=bool(raw.get("should_pass_to_kernel")),
        routing_reason=str(raw.get("routing_reason") or "validated router result"),
        safety_flags=[
            flag
            for flag in _coerce_str_list(raw.get("safety_flags"))
            if flag in SAFETY_FLAG_VOCABULARY
        ],
        advisory_latency_ms=_coerce_latency(raw.get("advisory_latency_ms")),
    )
    result["router_version"] = ROUTER_VERSION
    result["advisory_used"] = False

    if result["intent_type"] not in ALLOWED_INTENT_TYPES:
        return _unknown(routing_reason="invalid intent_type degraded to unknown_ambiguous")

    if _is_command_action(result["action"]):
        result["should_pass_to_kernel"] = False
        result["action"] = ""
        result["intent_type"] = "unknown_ambiguous"
        result["domain"] = "UNKNOWN"
        result["routing_reason"] = "COMMAND action blocked by cognitive router validation"
        return result

    if result["intent_type"] == "needs_context":
        result["should_pass_to_kernel"] = False
        if not result["missing_fields"]:
            return _unknown(routing_reason="needs_context without missing_fields degraded")
        return result

    if result["intent_type"] == "executable_intent":
        if result["confidence"] < 0.70:
            return _unknown(routing_reason="low-confidence executable intent degraded")
        if result["domain"] not in EXECUTABLE_DOMAINS:
            return _unknown(routing_reason="invalid executable domain degraded")
        result["should_pass_to_kernel"] = True
        return result

    result["should_pass_to_kernel"] = False
    return result


def route_text(text: str) -> RouterResult:
    """Route text deterministically without consulting LLMs or external services."""
    started = time.perf_counter()
    normalized = _normalize(text or "")
    result = _route_normalized_text(normalized)
    result["advisory_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return validate_router_result(result)


def _route_normalized_text(normalized: str) -> RouterResult:
    if not normalized:
        return _unknown(routing_reason="empty input")

    safety_flags = _detect_safety_flags(normalized)
    if safety_flags:
        return _unknown(
            routing_reason="input matched safety-sensitive override language",
            safety_flags=safety_flags,
        )

    if normalized in {"hola", "buenos dias", "buenas tardes", "buenas noches", "como estas", "hey"}:
        return _base_result(
            intent_type="conversational",
            domain="ASSISTANT",
            action="CHAT_RESPONSE",
            confidence=0.96,
            routing_reason="matched conversational greeting",
        )

    if _CAPABILITY_RE.match(normalized):
        return _base_result(
            intent_type="capability_summary",
            domain="ASSISTANT",
            action="CAPABILITY_SUMMARY",
            confidence=0.93,
            routing_reason="matched capability summary request",
        )

    if normalized in {"como esta el sistema", "estado del sistema", "salud del sistema", "que esta activo"}:
        return _base_result(
            intent_type="read_only_status",
            domain="SYSTEM",
            action="READ_ONLY_STATUS",
            confidence=0.94,
            routing_reason="matched read-only system status request",
        )

    if _REVIEW_QUEUE_RE.search(normalized):
        return _base_result(
            intent_type="review_queue_status",
            domain="ASSISTANT",
            action="REVIEW_QUEUE_STATUS",
            confidence=0.91,
            routing_reason="matched manual review queue status request",
        )

    code_result = _route_code(normalized)
    if code_result is not None:
        return code_result

    fin_result = _route_fin(normalized)
    if fin_result is not None:
        return fin_result

    work_result = _route_work(normalized)
    if work_result is not None:
        return work_result

    host_result = _route_host(normalized)
    if host_result is not None:
        return host_result

    if _PLAN_REQUEST_RE.search(normalized):
        return _base_result(
            intent_type="plan_request",
            domain="ASSISTANT",
            action="",
            confidence=0.88,
            routing_reason="matched plan-only / dry-run request",
        )

    return _unknown(routing_reason="no deterministic route matched", safety_flags=["unknown_intent"])


def _route_code(normalized: str) -> RouterResult | None:
    has_code_verb = bool(re.search(r"\b(?:analiza|analizar|revisa|revisar|audita|auditar)\b", normalized))
    has_code_subject = bool(re.search(r"\b(?:repo|repositorio|github|codigo|code)\b", normalized))
    if not (has_code_verb and has_code_subject):
        return None

    repo_match = _GITHUB_URL_RE.search(normalized)
    path_match = _PATH_RE.search(normalized)
    if repo_match or path_match:
        entities: dict[str, Any] = {}
        if repo_match:
            entities["repo_url"] = repo_match.group(0)
        if path_match:
            entities["path"] = path_match.group(0)
        return _base_result(
            intent_type="executable_intent",
            domain="CODE",
            action="CODE_REVIEW",
            confidence=0.84,
            entities=entities,
            should_pass_to_kernel=True,
            routing_reason="matched code review request with repository/path context",
        )

    return _base_result(
        intent_type="needs_context",
        domain="CODE",
        action="CODE_REVIEW",
        confidence=0.82,
        missing_fields=["repo_url"],
        routing_reason="code request is missing repository URL or path",
    )


def _route_fin(normalized: str) -> RouterResult | None:
    if not re.search(r"\b(?:gaste|gasto|pague|compre)\b", normalized):
        return None

    amount_match = _AMOUNT_RE.search(normalized)
    if not amount_match:
        return _base_result(
            intent_type="needs_context",
            domain="FIN",
            action="FIN_EXPENSE",
            confidence=0.83,
            missing_fields=["amount"],
            entities=_extract_category(normalized),
            routing_reason="expense request is missing amount",
        )

    entities = {"amount": amount_match.group(0)}
    entities.update(_extract_category(normalized))
    return _base_result(
        intent_type="executable_intent",
        domain="FIN",
        action="FIN_EXPENSE",
        confidence=0.86,
        entities=entities,
        should_pass_to_kernel=True,
        routing_reason="matched expense request with amount",
    )


def _route_work(normalized: str) -> RouterResult | None:
    if not re.search(r"\b(?:crea|crear)\b.*\btarea\b", normalized):
        return None

    title = normalized.split("tarea", 1)[1].strip(" :.-")
    if not title:
        return _base_result(
            intent_type="needs_context",
            domain="WORK",
            action="WORK_CREATE",
            confidence=0.81,
            missing_fields=["task_title"],
            routing_reason="task creation request is missing task title",
        )

    return _base_result(
        intent_type="executable_intent",
        domain="WORK",
        action="WORK_CREATE",
        confidence=0.87,
        entities={"task_title": title},
        should_pass_to_kernel=True,
        routing_reason="matched task creation request with title",
    )


def _route_host(normalized: str) -> RouterResult | None:
    match = re.match(r"^(?:abre|abrir|open)\s+(.+)$", normalized)
    if not match:
        return None

    target = match.group(1).strip()
    if not target:
        return _base_result(
            intent_type="needs_context",
            domain="HOST",
            action="HOST_OPEN_APP",
            confidence=0.75,
            missing_fields=["target"],
            routing_reason="host open request is missing target",
        )

    return _base_result(
        intent_type="executable_intent",
        domain="HOST",
        action="HOST_OPEN_APP",
        confidence=0.78,
        entities={"target": target},
        should_pass_to_kernel=True,
        routing_reason="matched host open request with explicit target",
    )


def _detect_safety_flags(normalized: str) -> list[str]:
    flags: list[str] = []
    if re.search(r"\b(?:ignora|omitir|bypassea|bypass|desactiva)\b.*\b(?:reglas|politica|policy|guardrails?)\b", normalized):
        flags.append("social_engineering")
    if re.search(r"\b(?:system prompt|prompt interno|instrucciones ocultas)\b", normalized):
        flags.append("prompt_injection")
    if re.search(r"\b(?:borra todo|elimina todo|format(?:ea|ear))\b", normalized):
        flags.append("destructive_request")
    return flags


def _extract_category(normalized: str) -> dict[str, str]:
    match = re.search(r"\ben\s+([a-z0-9_ -]+?)(?:\s+(?:ayer|hoy|manana)|$)", normalized)
    if not match:
        return {}
    category = match.group(1).strip()
    return {"category": category} if category else {}


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _coerce_latency(value: Any) -> float:
    try:
        latency = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, latency)


def _is_command_action(action: str) -> bool:
    upper = action.upper()
    return upper == "COMMAND" or upper.endswith("_COMMAND")
