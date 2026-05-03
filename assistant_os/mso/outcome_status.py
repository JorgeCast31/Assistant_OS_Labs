"""Read-only outcome/status producer for MSO observability."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from . import task_registry, trace_aggregator

OUTCOME_STATUSES = {"completed", "failed", "blocked", "pending", "unknown", "not_found"}
EXECUTION_STATUSES = {"real", "stub", "unavailable", "partial"}
EXECUTION_MODES = {"auto", "confirm", "clarify", "blocked"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked"}
SAFE_TEXT_LIMIT = 500
SAFE_SOURCE_ERROR_LIMIT = 200

SENSITIVE_KEYS = {
    "authorized_plan",
    "authority_artifact",
    "capability_material",
    "diff",
    "env",
    "environment",
    "file_content",
    "patch",
    "plan",
    "prompt",
    "raw_prompt",
    "raw_text",
    "secret",
    "signature",
    "stderr",
    "stdout",
    "token",
}
SENSITIVE_VALUE_TERMS = SENSITIVE_KEYS - {"plan"}
SENSITIVE_TERMS = tuple(sorted(SENSITIVE_VALUE_TERMS | {"authority artifacts", "secrets", "tokens"}))


def build_outcome_status(
    *,
    plan_id: str | None = None,
    context_id: str | None = None,
    trace_id: str | None = None,
    execution_id: str | None = None,
) -> dict:
    """Build a fail-soft read-only snapshot of known execution outcome evidence."""
    query = {
        "plan_id": _clean_str(plan_id),
        "context_id": _clean_str(context_id),
        "trace_id": _clean_str(trace_id),
        "execution_id": _clean_str(execution_id),
    }
    response = _empty_response(query)

    try:
        task = _source(
            response,
            "task_registry",
            lambda: _find_task(
                plan_id=query["plan_id"],
                context_id=query["context_id"],
                trace_id=query["trace_id"],
                execution_id=query["execution_id"],
            ),
        )
        if task is not None:
            response["sources"]["task_registry"] = True
            _merge_task(response, task)

        trace_chain = _source(
            response,
            "trace_chain",
            lambda: _find_trace_chain(
                plan_id=response["correlation"]["plan_id"] or query["plan_id"],
                context_id=response["correlation"]["context_id"] or query["context_id"],
                trace_id=response["correlation"]["trace_id"] or query["trace_id"],
                execution_id=response["correlation"]["execution_id"] or query["execution_id"],
            ),
        )
        if trace_chain is not None:
            response["sources"]["trace_chain"] = True
            _merge_trace_chain(response, trace_chain)

        pending = _source(
            response,
            "context_store_pending",
            lambda: _find_pending_context(
                plan_id=response["correlation"]["plan_id"] or query["plan_id"],
                context_id=response["correlation"]["context_id"] or query["context_id"],
            ),
        )
        if pending is not None:
            response["sources"]["context_store_pending"] = True
            _merge_pending_context(response, pending)

        runner_metadata = _source(
            response,
            "runner_metadata",
            lambda: _read_runner_metadata(response["correlation"]["execution_id"] or query["execution_id"]),
        )
        if runner_metadata is not None:
            response["sources"]["runner_metadata"] = True
            _merge_runner_metadata(response, runner_metadata)

        _finalize_response(response)
    except Exception as exc:  # pragma: no cover - last-ditch producer guard
        response["ok"] = False
        response["source_errors"].append(_source_error("producer", exc, limit=SAFE_SOURCE_ERROR_LIMIT))
        response["outcome"]["status"] = "unknown"

    return response


def _empty_response(query: dict[str, str]) -> dict:
    return {
        "ok": True,
        "found": False,
        "query": dict(query),
        "outcome": {
            "status": "unknown",
            "result_type": "",
            "execution_status": "unknown",
            "domain": "",
            "action": "",
            "message": "",
            "error_type": "",
            "error_message": "",
        },
        "correlation": {
            "context_id": "",
            "trace_id": "",
            "plan_id": "",
            "task_id": "",
            "execution_id": "",
            "policy_decision_ref": "",
            "governance_ref": "",
            "execution_mode": "unknown",
        },
        "sources": {
            "task_registry": False,
            "trace_chain": False,
            "context_store_pending": False,
            "runner_metadata": False,
        },
        "source_errors": [],
    }


def _source(response: dict, source: str, reader):
    try:
        return reader()
    except Exception as exc:
        response["source_errors"].append(_source_error(source, exc, limit=SAFE_SOURCE_ERROR_LIMIT))
        return None


def _source_error(source: str, exc: Exception, *, limit: int) -> dict[str, str]:
    return {
        "source": source,
        "error": _safe_text(f"{type(exc).__name__}: {exc}", limit=limit),
    }


def _find_task(*, plan_id: str, context_id: str, trace_id: str, execution_id: str):
    if not any((plan_id, context_id, trace_id, execution_id)):
        return None
    if plan_id:
        direct = _read_task(plan_id)
        if direct is not None:
            return direct
    for task in _read_tasks():
        if _record_matches(task, plan_id=plan_id, context_id=context_id, trace_id=trace_id, execution_id=execution_id):
            return task
    return None


def _read_task(task_id: str):
    return task_registry.get_task(task_id)


def _read_tasks():
    return task_registry.list_tasks()


def _find_trace_chain(*, plan_id: str, context_id: str, trace_id: str, execution_id: str):
    if not any((plan_id, context_id, trace_id, execution_id)):
        return None
    if plan_id:
        direct = trace_aggregator.get_trace_chain(plan_id)
        if direct is not None:
            return direct
    for chain in _read_trace_chains():
        execution = _as_dict(getattr(chain, "execution", {}))
        if (
            (plan_id and _clean_str(getattr(chain, "plan_id", "")) == plan_id)
            or (context_id and _clean_str(getattr(chain, "context_id", "")) == context_id)
            or (trace_id and _clean_str(getattr(chain, "trace_id", "")) == trace_id)
            or (execution_id and _clean_str(execution.get("execution_id")) == execution_id)
        ):
            return chain
    return None


def _read_trace_chains():
    return trace_aggregator.list_trace_chains(limit=500)


def _find_pending_context(*, plan_id: str, context_id: str) -> dict | None:
    lookup_ids = [item for item in (context_id, plan_id) if item]
    if not lookup_ids:
        return None

    from assistant_os import context_store

    with context_store._lock:  # type: ignore[attr-defined]
        for lookup_id in lookup_ids:
            stored = context_store._store.get(lookup_id)  # type: ignore[attr-defined]
            if stored is None:
                continue
            if context_store._is_expired(stored):  # type: ignore[attr-defined]
                continue
            return {"context_id": lookup_id, "stored": dict(stored)}
    return None


def _read_runner_metadata(execution_id: str) -> dict | None:
    execution_id = _clean_str(execution_id)
    if not execution_id or ".." in execution_id or "/" in execution_id or "\\" in execution_id:
        return None
    base = Path(__file__).resolve().parent.parent.parent / "var" / "runner" / "executions"
    metadata_path = base / execution_id / "metadata.json"
    try:
        metadata_path.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    if not metadata_path.exists():
        return None
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _merge_task(response: dict, task: Any) -> None:
    task_dict = _as_dict(task)
    _fill_correlation(response, "task_id", task_dict.get("task_id"))
    _fill_correlation(response, "context_id", task_dict.get("context_id"))
    _fill_correlation(response, "trace_id", task_dict.get("trace_id"))
    _fill_correlation(response, "plan_id", task_dict.get("plan_id"))
    _fill_correlation(response, "execution_id", task_dict.get("execution_id"))
    _fill_correlation(response, "policy_decision_ref", task_dict.get("decision_trace_ref"))
    _fill_correlation(response, "governance_ref", task_dict.get("governance_trace_ref"))
    _fill_execution_mode(response, task_dict.get("execution_mode"))

    _fill_outcome(response, "domain", task_dict.get("domain"))
    _fill_outcome(response, "action", task_dict.get("last_known_action"))
    _fill_outcome(response, "result_type", task_dict.get("result_type"))
    _fill_outcome(response, "error_type", task_dict.get("error_type"))
    _fill_outcome(response, "error_message", task_dict.get("error_message"))

    status = _clean_str(task_dict.get("status"))
    if status in OUTCOME_STATUSES:
        _set_status(response, status)


def _merge_trace_chain(response: dict, chain: Any) -> None:
    chain_dict = _as_dict(chain)
    _fill_correlation(response, "task_id", chain_dict.get("task_id"))
    _fill_correlation(response, "context_id", chain_dict.get("context_id"))
    _fill_correlation(response, "trace_id", chain_dict.get("trace_id"))
    _fill_correlation(response, "plan_id", chain_dict.get("plan_id"))
    _fill_correlation(response, "policy_decision_ref", chain_dict.get("decision_trace_ref"))
    _fill_correlation(response, "governance_ref", chain_dict.get("governance_trace_ref"))
    _fill_execution_mode(response, chain_dict.get("execution_mode"))

    _fill_outcome(response, "domain", chain_dict.get("domain"))
    _fill_outcome(response, "action", chain_dict.get("action"))

    execution = _as_dict(chain_dict.get("execution", {}))
    result = _as_dict(chain_dict.get("result", {}))
    if execution:
        _fill_correlation(response, "execution_id", execution.get("execution_id"))
        _fill_outcome(response, "result_type", execution.get("result_type"))
    if result:
        _merge_domain_result(response, result)

    governance_trace = _as_dict(chain_dict.get("governance_trace", {}))
    if governance_trace:
        _fill_correlation(response, "governance_ref", governance_trace.get("governance_ref"))
        _fill_execution_mode(response, governance_trace.get("effective_execution_mode"))
        if _is_blocked_governance(governance_trace):
            _set_status(response, "blocked")


def _merge_domain_result(response: dict, result: dict) -> None:
    _fill_outcome(response, "result_type", result.get("result_type"))
    _fill_outcome(response, "domain", result.get("domain"))
    _fill_outcome(response, "message", result.get("message"))
    _fill_outcome(response, "execution_status", _canonical_execution_status(result.get("execution_status")))
    _fill_correlation(response, "trace_id", result.get("trace_id"))
    _fill_correlation(response, "plan_id", result.get("plan_id"))

    error = _as_dict(result.get("error", {}))
    if error:
        _fill_outcome(response, "error_type", error.get("type") or error.get("code") or error.get("error_type"))
        _fill_outcome(response, "error_message", error.get("message") or error.get("detail") or error.get("error_message"))
    else:
        _fill_outcome(response, "error_type", result.get("error_type"))
        _fill_outcome(response, "error_message", result.get("error_message"))

    if _has_blocked_evidence(result):
        _set_status(response, "blocked")
    elif result.get("result_type") == "plan_confirmation_required":
        _set_status(response, "pending")
    elif result.get("ok") is True:
        _set_status(response, "completed")
    elif result.get("ok") is False:
        _set_status(response, "failed")


def _merge_pending_context(response: dict, pending: dict) -> None:
    stored = _as_dict(pending.get("stored", {}))
    plan = _as_dict(stored.get("plan", {}))
    _fill_correlation(response, "context_id", pending.get("context_id"))
    _fill_correlation(response, "plan_id", plan.get("plan_id") or plan.get("id"))
    _fill_correlation(response, "trace_id", plan.get("trace_id"))
    authority_context = _as_dict(plan.get("_authority_context", {}))
    _fill_correlation(response, "policy_decision_ref", authority_context.get("policy_decision_ref"))
    _fill_correlation(response, "governance_ref", authority_context.get("governance_ref"))
    _fill_execution_mode(response, authority_context.get("execution_mode") or plan.get("execution_mode"))
    _fill_outcome(response, "domain", plan.get("domain"))
    _fill_outcome(response, "action", plan.get("action") or stored.get("operation"))
    if response["outcome"]["status"] not in TERMINAL_TASK_STATUSES:
        _set_status(response, "pending")


def _merge_runner_metadata(response: dict, metadata: dict) -> None:
    _fill_correlation(response, "execution_id", metadata.get("execution_id"))
    final_status = _clean_str(metadata.get("final_status")).lower()
    status = _clean_str(metadata.get("status")).upper()
    if final_status == "success" or status == "SUCCESS":
        _set_status(response, "completed")
    elif final_status == "failed" or status in {"FAILED", "TESTS_FAILED"}:
        _set_status(response, "failed")
    elif status in {"PENDING", "RUNNING", "WORKSPACE_READY", "CHANGES_APPLIED", "TESTS_PASSED"}:
        if response["outcome"]["status"] in {"unknown", "not_found"}:
            _set_status(response, "pending")


def _finalize_response(response: dict) -> None:
    response["found"] = any(response["sources"].values())
    if not response["found"]:
        response["outcome"]["status"] = "unknown" if response["source_errors"] else "not_found"
    elif response["outcome"]["status"] not in OUTCOME_STATUSES:
        response["outcome"]["status"] = "unknown"
    if response["outcome"]["execution_status"] not in EXECUTION_STATUSES:
        response["outcome"]["execution_status"] = "unknown"
    if response["correlation"]["execution_mode"] not in EXECUTION_MODES:
        response["correlation"]["execution_mode"] = "unknown"


def _record_matches(record: Any, *, plan_id: str, context_id: str, trace_id: str, execution_id: str) -> bool:
    record_dict = _as_dict(record)
    return any(
        (
            plan_id and _clean_str(record_dict.get("plan_id")) == plan_id,
            context_id and _clean_str(record_dict.get("context_id")) == context_id,
            trace_id and _clean_str(record_dict.get("trace_id")) == trace_id,
            execution_id and _clean_str(record_dict.get("execution_id")) == execution_id,
        )
    )


def _fill_correlation(response: dict, key: str, value: Any) -> None:
    value = _safe_text(value)
    if value and not response["correlation"].get(key):
        response["correlation"][key] = value


def _fill_execution_mode(response: dict, value: Any) -> None:
    value = _clean_str(value).lower()
    if value in EXECUTION_MODES and response["correlation"]["execution_mode"] == "unknown":
        response["correlation"]["execution_mode"] = value


def _fill_outcome(response: dict, key: str, value: Any) -> None:
    if key == "execution_status":
        value = _canonical_execution_status(value)
    else:
        value = _safe_text(value)
    current = response["outcome"].get(key)
    if value and (not current or current == "unknown"):
        response["outcome"][key] = value


def _set_status(response: dict, status: str) -> None:
    if status in OUTCOME_STATUSES:
        response["outcome"]["status"] = status


def _canonical_execution_status(value: Any) -> str:
    value = _clean_str(value).lower()
    return value if value in EXECUTION_STATUSES else ""


def _is_blocked_governance(governance_trace: dict) -> bool:
    return (
        _clean_str(governance_trace.get("action")).upper() == "BLOCK"
        or _clean_str(governance_trace.get("effective_execution_mode")).lower() == "blocked"
        or _clean_str(governance_trace.get("capability_mode")).lower() == "deny"
    )


def _has_blocked_evidence(result: dict) -> bool:
    if _clean_str(result.get("result_type")).lower() in {"denied", "blocked", "policy_denied"}:
        return True
    error = _as_dict(result.get("error", {}))
    if _clean_str(error.get("code") or error.get("type")).lower() in {"blocked", "policy_violation", "governance_blocked"}:
        return True
    data = _as_dict(result.get("data", {}))
    return data.get("blocked") is True or data.get("governance_blocked") is True


def _safe_text(value: Any, *, limit: int = SAFE_TEXT_LIMIT) -> str:
    value = _scrub(value)
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if len(value) > limit:
        value = value[:limit] + "...[truncated]"
    return value


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[redacted]" if _is_sensitive_key(key) else _scrub(item))
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value[:10]]
    if isinstance(value, tuple):
        return tuple(_scrub(item) for item in value[:10])
    if isinstance(value, str):
        return _redact_sensitive_terms(value)
    return value


def _redact_sensitive_terms(value: str) -> str:
    redacted = value
    for term in SENSITIVE_TERMS:
        redacted = re.sub(re.escape(term), "[redacted]", redacted, flags=re.IGNORECASE)
    return redacted


def _is_sensitive_key(key: Any) -> bool:
    normalized = _clean_str(key).lower()
    return normalized in SENSITIVE_KEYS


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
