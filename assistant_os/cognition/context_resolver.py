"""Deterministic non-executable ContextRequest v0.

ContextRequest is short-lived chat state for collecting missing fields. It is
not a plan, task, confirmation, execution, or authority artifact.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


CONTEXT_REQUEST_TTL_SECONDS = 15 * 60
DEFAULT_MAX_ATTEMPTS = 3

_GITHUB_URL_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_FIN_VERBS_RE = re.compile(r"\b(?:gaste|gasto|pague|compre)\b", re.IGNORECASE)
_ITBMS_YES_RE = re.compile(r"\b(?:si|sí|con)\b.*\bitbms\b|\bitbms\b.*\b(?:si|sí|con)\b", re.IGNORECASE)
_ITBMS_NO_RE = re.compile(r"\b(?:no|sin)\b.*\bitbms\b|\bitbms\b.*\b(?:no|sin)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"^\s*(?:cancelar|cancela|cancel|olvida|descarta|no)\s*$", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=CONTEXT_REQUEST_TTL_SECONDS)).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_expired(context_request: dict[str, Any]) -> bool:
    expires = _parse_iso(str(context_request.get("expires_at") or ""))
    if expires is None:
        return True
    return datetime.now(timezone.utc) > expires


def _sanitize_context_request(context_request: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"plan_id", "confirm_plan_id", "task_id", "execution_mode", "execution_status"}
    clean = {k: v for k, v in dict(context_request).items() if k not in forbidden}
    clean["non_executable"] = True
    clean["executable"] = False
    return clean


def _prompt_for(domain: str, missing_fields: list[str]) -> str:
    missing = set(missing_fields)
    if domain == "CODE" and "repo_url" in missing:
        return "Necesito el URL del repositorio para continuar."
    if domain == "FIN":
        if missing == {"responsable"}:
            return "Necesito el responsable del gasto."
        if missing == {"itbms"}:
            return "Necesito saber si el gasto incluye ITBMS."
        if missing:
            return "Necesito el responsable y si incluye ITBMS."
    return "Necesito un poco mas de contexto para continuar."


def make_context_request(
    *,
    domain: str,
    action: str,
    missing_fields: list[str],
    collected: dict[str, Any] | None,
    original_text: str,
    prompted_question: str,
    context_id: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    context_request = {
        "id": str(uuid.uuid4()),
        "domain": domain,
        "action": action,
        "non_executable": True,
        "executable": False,
        "missing_fields": list(missing_fields),
        "collected": dict(collected or {}),
        "entities": dict(collected or {}),
        "original_text": original_text,
        "prompted_question": prompted_question,
        "context_id": context_id,
        "created_at": now_iso(),
        "expires_at": _expires_at(),
        "resolution_attempts": 0,
        "max_attempts": max_attempts,
        "ready_to_submit": False,
    }
    return _sanitize_context_request(context_request)


def maybe_create_fin_context_request(text: str, normalized: str, context_id: str) -> dict[str, Any] | None:
    if not _FIN_VERBS_RE.search(normalized):
        return None
    amount = _AMOUNT_RE.search(normalized)
    if not amount:
        return None

    collected: dict[str, Any] = {"amount": amount.group(0)}
    if "comida" in normalized:
        collected["category"] = "comida"
    if "ayer" in normalized:
        collected["date"] = "ayer"

    missing_fields = ["responsable", "itbms"]
    return make_context_request(
        domain="FIN",
        action="FIN_EXPENSE",
        missing_fields=missing_fields,
        collected=collected,
        original_text=text,
        prompted_question=_prompt_for("FIN", missing_fields),
        context_id=context_id,
    )


def make_code_repo_context_request(text: str, context_id: str) -> dict[str, Any]:
    missing_fields = ["repo_url"]
    return make_context_request(
        domain="CODE",
        action="CODE_REVIEW",
        missing_fields=missing_fields,
        collected={},
        original_text=text,
        prompted_question=_prompt_for("CODE", missing_fields),
        context_id=context_id,
    )


def resolve_context_request(
    context_request: dict[str, Any],
    text: str,
    *,
    context_id: str,
) -> dict[str, Any]:
    current = _sanitize_context_request(context_request)
    if _is_expired(current):
        return {"status": "expired", "context_request": None}

    if _CANCEL_RE.match(text or ""):
        return {"status": "cancelled", "context_request": None}

    domain = str(current.get("domain") or "")
    collected = dict(current.get("collected") or current.get("entities") or {})
    missing_fields = list(current.get("missing_fields") or [])
    found_any = False

    if domain == "CODE":
        match = _GITHUB_URL_RE.search(text or "")
        if match and "repo_url" in missing_fields:
            collected["repo_url"] = match.group(0)
            missing_fields = [f for f in missing_fields if f != "repo_url"]
            found_any = True

    if domain == "FIN":
        normalized = _normalize_text(text)
        if "itbms" in missing_fields:
            if _ITBMS_YES_RE.search(normalized):
                collected["itbms"] = True
                missing_fields = [f for f in missing_fields if f != "itbms"]
                found_any = True
            elif _ITBMS_NO_RE.search(normalized):
                collected["itbms"] = False
                missing_fields = [f for f in missing_fields if f != "itbms"]
                found_any = True
        if "responsable" in missing_fields:
            responsable = _extract_responsable(text)
            if responsable:
                collected["responsable"] = responsable
                missing_fields = [f for f in missing_fields if f != "responsable"]
                found_any = True

    attempts = int(current.get("resolution_attempts") or 0)
    if not found_any:
        attempts += 1

    updated = dict(current)
    updated["context_id"] = context_id
    updated["collected"] = collected
    updated["entities"] = dict(collected)
    updated["missing_fields"] = missing_fields
    updated["resolution_attempts"] = attempts
    updated["prompted_question"] = _prompt_for(domain, missing_fields)
    updated["ready_to_submit"] = not missing_fields
    updated = _sanitize_context_request(updated)

    if not found_any:
        return {"status": "no_progress", "context_request": updated}
    if missing_fields:
        return {"status": "partial", "context_request": updated}
    return {"status": "complete", "context_request": updated}


def _normalize_text(text: str) -> str:
    replacements = str.maketrans({"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u"})
    return (text or "").lower().translate(replacements).strip()


def _extract_responsable(text: str) -> str:
    raw = (text or "").strip()
    normalized = _normalize_text(raw)
    if not raw or normalized in {"yo", "mi", "mio", "mia"}:
        return ""
    if "itbms" in normalized:
        return ""
    if _GITHUB_URL_RE.search(raw):
        return ""
    words = [w.strip(" ,.;:!?") for w in raw.split() if w.strip(" ,.;:!?")]
    if len(words) == 1 and words[0].isalpha() and words[0].lower() not in {"si", "sí", "no"}:
        return words[0]
    return ""


__all__ = [
    "make_code_repo_context_request",
    "make_context_request",
    "maybe_create_fin_context_request",
    "resolve_context_request",
]
