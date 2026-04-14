"""Local LLM adapter for guarded advisory consultation.

Sprint 2 constraints:
- advisory only
- feature-flagged
- safe timeout / exception isolation
- no deterministic routing replacement
- Ollama-compatible HTTP API as first provider
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from .contracts import (
    LocalLlmAdvisory,
    LocalLlmRequest,
    LocalLlmResponse,
    LocalLlmStatus,
)
from .prompts import build_orchestrator_advisory_prompt
from ..config import (
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_PROVIDER,
    LOCAL_LLM_TIMEOUT_SECONDS,
    MSO_ENABLED,
)

_log = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = frozenset({"ollama"})


def _normalized_provider() -> str:
    return (LOCAL_LLM_PROVIDER or "").strip().lower()


def is_enabled() -> bool:
    """Return True only when the feature flag and provider config are both valid."""
    return bool(
        MSO_ENABLED
        and _normalized_provider() in _SUPPORTED_PROVIDERS
        and LOCAL_LLM_BASE_URL
        and LOCAL_LLM_MODEL
    )


def _disabled_response(reason: str = "") -> LocalLlmResponse:
    return {
        "status": "disabled",
        "provider": _normalized_provider(),
        "model": LOCAL_LLM_MODEL,
        "advisory": {},
        "latency_ms": 0,
        "error": reason or None,
    }


def _error_response(error: str, latency_ms: int = 0) -> LocalLlmResponse:
    return {
        "status": "error",
        "provider": _normalized_provider(),
        "model": LOCAL_LLM_MODEL,
        "advisory": {},
        "latency_ms": latency_ms,
        "error": error,
    }


def _build_advisory_prompt(req: LocalLlmRequest) -> str:
    task = req.get("task", "orchestrator_advisory")
    if task in {"orchestrator_advisory", "orchestrator_advisory_bundle", "probe"}:
        return build_orchestrator_advisory_prompt(req)

    return build_orchestrator_advisory_prompt(req)


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return None

    try:
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw_text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_advisory(data: dict[str, Any]) -> LocalLlmAdvisory:
    constraints = data.get("constraints", [])
    risk_notes = data.get("risk_notes", [])
    if not isinstance(constraints, list):
        constraints = [constraints] if constraints else []
    if not isinstance(risk_notes, list):
        risk_notes = [risk_notes] if risk_notes else []
    return {
        "reasoning_summary": str(data.get("reasoning_summary", "")).strip(),
        "routing_hint": str(data.get("routing_hint", "")).strip(),
        "suggested_domain": str(data.get("suggested_domain", "")).strip(),
        "suggested_action": str(data.get("suggested_action", "")).strip(),
        "execution_posture_hint": str(data.get("execution_posture_hint", "")).strip(),
        "confidence_note": str(data.get("confidence_note", "")).strip(),
        "code_task_summary": str(data.get("code_task_summary", "")).strip(),
        "repo_context": str(data.get("repo_context", "")).strip(),
        "constraints": [str(item).strip() for item in constraints if str(item).strip()],
        "expected_artifact": str(data.get("expected_artifact", "")).strip(),
        "risk_notes": [str(item).strip() for item in risk_notes if str(item).strip()],
    }


def _ollama_generate(prompt: str) -> tuple[dict[str, Any] | None, str | None, int]:
    started = time.perf_counter()
    url = LOCAL_LLM_BASE_URL.rstrip("/") + "/api/generate"
    payload = {
        "model": LOCAL_LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    try:
        response = requests.post(url, json=payload, timeout=LOCAL_LLM_TIMEOUT_SECONDS)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        body = response.json()
    except requests.Timeout:
        return None, f"Local LLM timeout after {LOCAL_LLM_TIMEOUT_SECONDS:.1f}s", int((time.perf_counter() - started) * 1000)
    except requests.RequestException as exc:
        return None, f"Local LLM request failed: {exc}", int((time.perf_counter() - started) * 1000)
    except ValueError as exc:
        return None, f"Local LLM returned non-JSON envelope: {exc}", int((time.perf_counter() - started) * 1000)

    raw_text = str(body.get("response", "")).strip()
    parsed = _extract_json_object(raw_text)
    if parsed is None:
        return None, "Local LLM returned invalid advisory JSON", latency_ms
    return parsed, None, latency_ms


def consult_advisory(req: LocalLlmRequest) -> LocalLlmResponse:
    """Consult the configured local model for an advisory-only summary."""
    provider = _normalized_provider()
    if not is_enabled():
        return _disabled_response("Local advisory disabled or incomplete configuration")

    if provider != "ollama":
        return _error_response(f"Unsupported local LLM provider: {provider}")

    prompt = _build_advisory_prompt(req)
    parsed, error, latency_ms = _ollama_generate(prompt)
    if error:
        _log.debug("local_llm advisory error: %s", error)
        return _error_response(error, latency_ms=latency_ms)

    return {
        "status": "ok",
        "provider": provider,
        "model": LOCAL_LLM_MODEL,
        "advisory": _normalize_advisory(parsed or {}),
        "latency_ms": latency_ms,
        "error": None,
    }


def probe_local_llm(*, roundtrip: bool = True) -> LocalLlmStatus:
    """Probe reachability and optional roundtrip for the configured local provider."""
    provider = _normalized_provider()
    status: LocalLlmStatus = {
        "enabled": is_enabled(),
        "provider": provider,
        "base_url": LOCAL_LLM_BASE_URL,
        "model": LOCAL_LLM_MODEL,
        "reachable": False,
        "model_available": False,
        "roundtrip_ok": False,
        "latency_ms": 0,
        "error": None,
    }
    if not is_enabled():
        status["error"] = "Local advisory disabled or incomplete configuration"
        return status

    if provider != "ollama":
        status["error"] = f"Unsupported local LLM provider: {provider}"
        return status

    started = time.perf_counter()
    tags_url = LOCAL_LLM_BASE_URL.rstrip("/") + "/api/tags"
    try:
        response = requests.get(tags_url, timeout=LOCAL_LLM_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        status["reachable"] = True
        models = body.get("models", [])
        status["model_available"] = any(
            str(m.get("name", "")).startswith(LOCAL_LLM_MODEL) for m in models if isinstance(m, dict)
        )
    except requests.Timeout:
        status["error"] = f"Local LLM probe timeout after {LOCAL_LLM_TIMEOUT_SECONDS:.1f}s"
        status["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return status
    except requests.RequestException as exc:
        status["error"] = f"Local LLM probe failed: {exc}"
        status["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return status
    except ValueError as exc:
        status["error"] = f"Local LLM probe returned invalid JSON: {exc}"
        status["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return status

    status["latency_ms"] = int((time.perf_counter() - started) * 1000)
    if not roundtrip:
        return status

    advisory = consult_advisory(
        {
            "task": "probe",
            "text": "healthcheck ping",
            "classifier_operation": "PROBE",
            "classifier_domain": "MSO",
            "planned_action": "PROBE",
        }
    )
    status["roundtrip_ok"] = advisory.get("status") == "ok"
    if advisory.get("status") != "ok":
        status["error"] = advisory.get("error")
    return status
