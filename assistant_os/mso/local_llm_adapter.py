"""Local LLM adapter for guarded advisory consultation.

Supported providers
-------------------
- ollama    : Ollama-compatible HTTP API  (/api/generate, /api/tags)
- llamacpp  : llama.cpp native server     (POST /completion, GET /health)

Constraints (unchanged from Sprint 2):
- advisory only
- feature-flagged via MSO_ENABLED + LOCAL_LLM_PROVIDER
- safe timeout / exception isolation
- no deterministic routing replacement
- all output validated before use
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

# M30: llamacpp added alongside ollama
_SUPPORTED_PROVIDERS = frozenset({"ollama", "llamacpp"})


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
    """Extract the first JSON object from raw text. Returns None on failure."""
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


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# llama.cpp backend (M30)
# ---------------------------------------------------------------------------

# llama.cpp server API shape (native, not OpenAI-compat):
#   POST /completion  { prompt, n_predict, temperature, stop, stream }
#                  → { content, stop, tokens_predicted, ... }
#   GET  /health   → { status: "ok" }  or HTTP 503 when loading

_LLAMACPP_N_PREDICT = 512       # max tokens for advisory completions
_LLAMACPP_STOP_TOKENS = ["\n\n", "```", "User:", "Assistant:"]


def _llamacpp_complete(prompt: str) -> tuple[dict[str, Any] | None, str | None, int]:
    """
    Call the llama.cpp native /completion endpoint.

    Returns (parsed_dict, error_string, latency_ms).
    On any failure the error_string is set and parsed_dict is None.
    """
    started = time.perf_counter()
    url = LOCAL_LLM_BASE_URL.rstrip("/") + "/completion"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "n_predict": _LLAMACPP_N_PREDICT,
        "temperature": 0.1,
        "stop": _LLAMACPP_STOP_TOKENS,
        "stream": False,
    }
    # llama.cpp ignores unknown fields; include model only if non-empty
    if LOCAL_LLM_MODEL:
        payload["model"] = LOCAL_LLM_MODEL

    try:
        response = requests.post(url, json=payload, timeout=LOCAL_LLM_TIMEOUT_SECONDS)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        body = response.json()
    except requests.Timeout:
        return None, f"llamacpp timeout after {LOCAL_LLM_TIMEOUT_SECONDS:.1f}s", int((time.perf_counter() - started) * 1000)
    except requests.RequestException as exc:
        return None, f"llamacpp request failed: {exc}", int((time.perf_counter() - started) * 1000)
    except ValueError as exc:
        return None, f"llamacpp returned non-JSON envelope: {exc}", int((time.perf_counter() - started) * 1000)

    # llama.cpp returns generated text in the "content" field
    raw_text = str(body.get("content", "")).strip()
    if not raw_text:
        return None, "llamacpp returned empty content", latency_ms

    parsed = _extract_json_object(raw_text)
    if parsed is None:
        return None, "llamacpp returned non-JSON advisory content", latency_ms
    return parsed, None, latency_ms


def _llamacpp_probe_health() -> tuple[bool, str | None, int]:
    """
    Probe the llama.cpp /health endpoint.

    Returns (reachable, error_string, latency_ms).
    llama.cpp /health returns {"status": "ok"} when ready,
    {"status": "loading model"} when still loading (503).
    We treat both HTTP 200 AND 503-with-loading as "reachable".
    """
    started = time.perf_counter()
    url = LOCAL_LLM_BASE_URL.rstrip("/") + "/health"

    try:
        response = requests.get(url, timeout=LOCAL_LLM_TIMEOUT_SECONDS)
        latency_ms = int((time.perf_counter() - started) * 1000)
    except requests.Timeout:
        return False, f"llamacpp health timeout after {LOCAL_LLM_TIMEOUT_SECONDS:.1f}s", int((time.perf_counter() - started) * 1000)
    except requests.RequestException as exc:
        return False, f"llamacpp health probe failed: {exc}", int((time.perf_counter() - started) * 1000)

    # 200 = fully ready; 503 with "loading model" = reachable but not ready yet
    if response.status_code == 200:
        return True, None, latency_ms

    if response.status_code == 503:
        try:
            body = response.json()
            # Guard: body must be a dict before calling .get()
            # llama.cpp returns {"status": "loading model"} but a non-dict
            # response body (e.g. string, list, null) must not raise here.
            if isinstance(body, dict) and "loading" in str(body.get("status", "")).lower():
                return True, "Model still loading", latency_ms
        except ValueError:
            pass  # Non-JSON 503 → treat as unreachable

    return False, f"llamacpp health returned HTTP {response.status_code}", latency_ms


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

def consult_advisory(req: LocalLlmRequest) -> LocalLlmResponse:
    """Consult the configured local model for an advisory-only summary."""
    provider = _normalized_provider()
    if not is_enabled():
        return _disabled_response("Local advisory disabled or incomplete configuration")

    if provider not in _SUPPORTED_PROVIDERS:
        return _error_response(f"Unsupported local LLM provider: {provider}")

    prompt = _build_advisory_prompt(req)

    if provider == "ollama":
        parsed, error, latency_ms = _ollama_generate(prompt)
    else:  # llamacpp
        parsed, error, latency_ms = _llamacpp_complete(prompt)

    if error:
        _log.debug("local_llm advisory error (%s): %s", provider, error)
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

    if provider not in _SUPPORTED_PROVIDERS:
        status["error"] = f"Unsupported local LLM provider: {provider}"
        return status

    # ── Provider-specific health probe ──────────────────────────────────────
    if provider == "ollama":
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

    elif provider == "llamacpp":
        reachable, err, lat = _llamacpp_probe_health()
        status["reachable"] = reachable
        status["latency_ms"] = lat
        if not reachable:
            status["error"] = err
            return status
        # For llama.cpp, "model available" means the server responded healthy.
        # The specific model is embedded in the running server — no listing endpoint.
        if err and "loading" in err.lower():
            status["model_available"] = False
            status["error"] = err
        else:
            status["model_available"] = True
            status["error"] = err  # may be None

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
