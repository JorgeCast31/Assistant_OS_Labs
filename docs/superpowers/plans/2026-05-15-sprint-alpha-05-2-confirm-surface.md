# SPRINT-ALPHA-05.2 — Prepared Action Review / Confirm Surface v0

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the "user review → human confirmation signal" segment of the operability loop — operator sees a prepared action, presses Confirm or Reject, a `HumanConfirmationRecord` is written, the queue view updates, and execution remains closed.

**Architecture:** A `HumanConfirmationRecord` frozen dataclass (in-memory store, threading.Lock) records the operator's signal separately from the frozen queue entries. `GET /mso/prepared-actions/pending` merges the record into each item. A new `POST /mso/prepared-actions/confirm` endpoint writes the record. A Next.js proxy forwards it. A button in `PreparedActionDetailPanel` drives the action. No authority chain step is satisfied; `execution_allowed` and `can_execute_now` remain `False` throughout.

**Tech Stack:** Python 3.12 (frozen dataclasses, threading.Lock, pytest), Next.js 14 App Router (server-side proxy with `getWebhookBaseUrl()` / `getWebhookHeaders()`), React (`useState`), Zustand (`usePreparedActionsStore`).

---

## Diagnostic Summary

### Operability Loop Map

| Node | State | File | Reachable UI | Reachable MSO | Tests |
|------|-------|------|-------------|--------------|-------|
| MSO chat → plan_request | ✅ Real | `surface_behavior.py` | Yes | Yes | Yes |
| plan_request → MSOExecutionProposal | ✅ Real | `mso/execution_proposal.py` | Yes | Yes | Yes |
| MSOExecutionProposal → AuthorityPreparationRequest | ✅ Real | `mso/authority_preparation.py` | Yes | Yes | Yes (791-line test file) |
| AuthorityPreparationRequest → ConfirmablePreparedAction | ✅ Real | `mso/confirmable_prepared_action.py` | Yes | Yes | Yes (584 lines) |
| ConfirmablePreparedAction → Queue | ✅ Real | `mso/prepared_action_queue.py` | Yes | Yes | Yes (953 lines) |
| Queue → Mission Control visibility | ✅ Real | `webhook_server.py` + `ConfirmFlowQueuePanel.tsx` | Yes | Partial | Partial |
| User inspection | ✅ Read-only | `PreparedActionDetailPanel.tsx` | Yes | No | Partial |
| **Human confirmation signal** | ❌ **MISSING** | — | **No** | **No** | **No** |
| PolicyDecision | ❌ Missing | — | No | No | No |
| CapabilityToken | ❌ Missing | — | No | No | No |
| OperationBinding | ❌ Missing | — | No | No | No |
| AuthorizedPlan | ❌ Missing | — | No | No | No |
| Police Gate check | ⚙️ Structural | `police/enforcement.py` | No | No | Yes (contract) |
| Runner / execution | ⚙️ Structural | `runner.py` | No | No | Yes |
| Outcome status | ✅ Observational | `mso/outcome_status.py` + `OutcomeStatusPanel.tsx` | Yes | No | Yes |
| MSO interpretation of outcome | ❌ Missing | — | No | No | No |

### Next Missing Link: Human Confirmation Signal

`sendMSOConfirmation()` in `ui/lib/sovereign/api.ts` exists but sends `'confirmar'` or `'cancelar'` as plain chat text to `mso_direct`. It is not a structured signal and has no backend handler.

There is:
- **No** `POST /mso/prepared-actions/confirm` endpoint
- **No** `HumanConfirmationRecord` or confirmation store
- **No** Confirm/Reject button in `PreparedActionDetailPanel`
- **No** merge of confirmation state into the pending-queue API response

The `ConfirmablePreparedActionQueueEntry` enforces `human_confirmation_status="pending"` as a frozen invariant in `__post_init__`. A separate record store is required — we cannot mutate frozen dataclass instances.

### Confirmed Sprint: SPRINT-ALPHA-05.2 — Prepared Action Review / Confirm Surface v0

This sprint does **not** satisfy any step in the authority chain. Execution stays closed. It closes exactly one real segment: operator review → governed confirmation signal.

---

## Hard Constraints (do not violate)

- `execution_allowed` stays `False` on every artifact throughout this sprint
- `can_execute_now` stays `False`
- `confirmed` on `ConfirmablePreparedAction` stays `False` (it is frozen; this sprint adds a separate record)
- No new authority semantics, Police semantics, CapabilityToken semantics, AuthorizedPlan semantics
- No new queue infrastructure — the existing `prepared_action_queue` is unchanged
- No visual redesign beyond the two buttons + status display
- Do not touch `police/enforcement.py`, `runner.py`, or any authority-chain module

---

## Files

**Create:**
- `assistant_os/mso/human_confirmation.py`
- `tests/test_human_confirmation.py`
- `tests/test_mso_prepared_actions_confirm_endpoint.py`
- `ui/app/api/mso/prepared-actions/confirm/route.ts`

**Modify:**
- `assistant_os/webhook_server.py` — add POST route + handler; merge confirmation in GET handler
- `ui/lib/types.ts` — add `ConfirmPreparedActionResult`; add two optional fields to `PreparedActionQueueEntry`
- `ui/lib/sovereign/api.ts` — add `confirmPreparedAction()`
- `ui/components/sovereign/PreparedActionDetailPanel.tsx` — add Confirm/Reject buttons

---

## Task 1: HumanConfirmationRecord Module (TDD)

**Files:**
- Create: `assistant_os/mso/human_confirmation.py`
- Test: `tests/test_human_confirmation.py`

- [ ] **Step 1.1 — Write the failing tests**

```python
# tests/test_human_confirmation.py
"""Tests for HumanConfirmationRecord — S-HUMAN-CONFIRM-01."""
import pytest
from assistant_os.mso.human_confirmation import (
    HumanConfirmationRecord,
    record_human_confirmation,
    get_human_confirmation,
    merge_confirmation_into_dict,
    clear_human_confirmation_store_for_tests,
)


@pytest.fixture(autouse=True)
def clear_store():
    clear_human_confirmation_store_for_tests()
    yield
    clear_human_confirmation_store_for_tests()


def test_confirmed_true_sets_status():
    r = HumanConfirmationRecord(entry_id="e1", action_id="a1", confirmed=True)
    assert r.execution_allowed is False
    d = r.to_dict()
    assert d["human_confirmation_status"] == "human_confirmed"
    assert d["execution_allowed"] is False
    assert d["can_execute_now"] is False
    assert "recorded_at" in d and "T" in d["recorded_at"]


def test_confirmed_false_sets_status():
    r = HumanConfirmationRecord(entry_id="e1", action_id="a1", confirmed=False)
    assert r.to_dict()["human_confirmation_status"] == "human_rejected"


def test_execution_allowed_enforced():
    with pytest.raises(ValueError, match="execution_allowed must be False"):
        HumanConfirmationRecord(entry_id="e1", action_id="a1", confirmed=True, execution_allowed=True)


def test_empty_entry_id_raises():
    with pytest.raises(ValueError, match="entry_id"):
        HumanConfirmationRecord(entry_id="", action_id="a1", confirmed=True)


def test_empty_action_id_raises():
    with pytest.raises(ValueError, match="action_id"):
        HumanConfirmationRecord(entry_id="e1", action_id="", confirmed=True)


def test_record_and_retrieve():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True, operator_note="lgtm")
    result = get_human_confirmation("e1")
    assert result is not None
    assert result.confirmed is True
    assert result.operator_note == "lgtm"
    assert result.execution_allowed is False


def test_get_none_for_unknown():
    assert get_human_confirmation("nonexistent") is None


def test_double_record_overwrites():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True)
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=False)
    assert get_human_confirmation("e1").confirmed is False


def test_merge_injects_status_when_record_exists():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True, operator_note="ok")
    merged = merge_confirmation_into_dict({"queue_entry_id": "e1", "human_confirmation_status": "pending"})
    assert merged["human_confirmation_status"] == "human_confirmed"
    assert "confirmation_recorded_at" in merged
    assert merged["operator_note"] == "ok"


def test_merge_is_noop_when_no_record():
    d = {"queue_entry_id": "e99", "human_confirmation_status": "pending"}
    merged = merge_confirmation_into_dict(d)
    assert merged["human_confirmation_status"] == "pending"
    assert "confirmation_recorded_at" not in merged


def test_merge_does_not_set_execution_allowed():
    record_human_confirmation(entry_id="e1", action_id="a1", confirmed=True)
    merged = merge_confirmation_into_dict({"queue_entry_id": "e1", "execution_allowed": False})
    assert merged.get("execution_allowed") is False
```

- [ ] **Step 1.2 — Run to confirm failure**

```
pytest tests/test_human_confirmation.py -v
```

Expected: `ModuleNotFoundError: No module named 'assistant_os.mso.human_confirmation'`

- [ ] **Step 1.3 — Implement the module**

```python
# assistant_os/mso/human_confirmation.py
"""
HumanConfirmationRecord — immutable record of operator review signal.

Records that a human operator has reviewed a ConfirmablePreparedAction and
signalled confirm or reject. Does NOT grant execution authority, issue tokens,
satisfy any step in the authority chain (PolicyDecision → CapabilityToken →
OperationBinding → AuthorizedPlan → PoliceGate), or change execution_allowed.

Spec: S-HUMAN-CONFIRM-01
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


@dataclass(frozen=True, kw_only=True)
class HumanConfirmationRecord:
    record_id: str = field(default_factory=_new_id)
    entry_id: str
    action_id: str
    confirmed: bool
    operator_note: str = ""
    recorded_at: datetime = field(default_factory=_now)
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.action_id:
            raise ValueError("action_id must be non-empty")
        if self.execution_allowed is not False:
            raise ValueError(
                "execution_allowed must be False — confirmation does not authorize execution"
            )

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "confirmed": self.confirmed,
            "operator_note": self.operator_note,
            "recorded_at": self.recorded_at.isoformat(),
            "human_confirmation_status": "human_confirmed" if self.confirmed else "human_rejected",
            "execution_allowed": False,
            "can_execute_now": False,
        }


_lock = threading.Lock()
_store: dict[str, HumanConfirmationRecord] = {}


def record_human_confirmation(
    *,
    entry_id: str,
    action_id: str,
    confirmed: bool,
    operator_note: str = "",
) -> HumanConfirmationRecord:
    record = HumanConfirmationRecord(
        entry_id=entry_id,
        action_id=action_id,
        confirmed=confirmed,
        operator_note=operator_note,
    )
    with _lock:
        _store[entry_id] = record
    return record


def get_human_confirmation(entry_id: str) -> HumanConfirmationRecord | None:
    with _lock:
        return _store.get(entry_id)


def merge_confirmation_into_dict(entry_dict: dict) -> dict:
    """Overlay human_confirmation_status onto a prepared-action dict if a record exists.

    Does not set execution_allowed or can_execute_now — those remain False as
    enforced by the queue entry invariants.
    """
    entry_id = entry_dict.get("queue_entry_id") or entry_dict.get("entry_id")
    if not entry_id:
        return entry_dict
    record = get_human_confirmation(entry_id)
    if record is None:
        return entry_dict
    return {
        **entry_dict,
        "human_confirmation_status": "human_confirmed" if record.confirmed else "human_rejected",
        "confirmation_recorded_at": record.recorded_at.isoformat(),
        "operator_note": record.operator_note,
    }


def clear_human_confirmation_store_for_tests() -> None:
    with _lock:
        _store.clear()
```

- [ ] **Step 1.4 — Run tests, expect pass**

```
pytest tests/test_human_confirmation.py -v
```

Expected: 11 tests PASS.

- [ ] **Step 1.5 — Commit**

```bash
git add assistant_os/mso/human_confirmation.py tests/test_human_confirmation.py
git commit -m "feat(mso): add HumanConfirmationRecord for operator review signal"
```

---

## Task 2: Merge Confirmation Status into GET Response (TDD)

**Files:**
- Modify: `assistant_os/webhook_server.py` — `_handle_mso_prepared_actions_pending_get()`
- Test: `tests/test_mso_prepared_actions_confirm_endpoint.py` (partial — the merge tests)

The GET handler currently calls `list_pending_confirmable_action_dicts()`. Each returned dict has `human_confirmation_status: "pending"` (frozen invariant). After this task, it calls `merge_confirmation_into_dict()` on each item so the UI reflects recorded confirmations.

- [ ] **Step 2.1 — Write failing merge tests**

Add to `tests/test_mso_prepared_actions_confirm_endpoint.py`:

```python
# tests/test_mso_prepared_actions_confirm_endpoint.py
"""Tests for POST /mso/prepared-actions/confirm and GET merge behavior."""
import json
import pytest
from assistant_os.mso.human_confirmation import (
    record_human_confirmation,
    get_human_confirmation,
    clear_human_confirmation_store_for_tests,
)
from assistant_os.mso.prepared_action_queue import (
    enqueue_confirmable_prepared_action,
    list_pending_confirmable_action_dicts,
    clear_confirmable_action_queue_for_tests,
)
from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
from assistant_os.mso.execution_proposal import build_execution_proposal


@pytest.fixture(autouse=True)
def clear_stores():
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()
    yield
    clear_human_confirmation_store_for_tests()
    clear_confirmable_action_queue_for_tests()


def _make_queue_entry(intent: str = "plan the architecture docs"):
    proposal = build_execution_proposal(
        user_intent=intent,
        domain="CODE",
        requested_action="plan_architecture_docs",
        capability_name="code_docs",
        capability_scope=["read", "write"],
    )
    preparation = prepare_authority_from_proposal(proposal)
    confirmable = build_confirmable_from_preparation(preparation)
    return enqueue_confirmable_prepared_action(confirmable)


# ── Merge tests ─────────────────────────────────────────────────────────────

def test_pending_dicts_show_pending_by_default():
    _make_queue_entry()
    items = list_pending_confirmable_action_dicts()
    assert len(items) == 1
    assert items[0]["human_confirmation_status"] == "pending"


def test_pending_dicts_reflect_confirmation_after_merge():
    entry = _make_queue_entry()
    entry_id = entry.queue_entry_id
    action_id = entry.prepared_action_id

    record_human_confirmation(entry_id=entry_id, action_id=action_id, confirmed=True)

    from assistant_os.mso.human_confirmation import merge_confirmation_into_dict
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]

    assert merged[0]["human_confirmation_status"] == "human_confirmed"
    assert "confirmation_recorded_at" in merged[0]


def test_pending_dicts_reflect_rejection_after_merge():
    entry = _make_queue_entry()
    record_human_confirmation(
        entry_id=entry.queue_entry_id, action_id=entry.prepared_action_id, confirmed=False
    )
    from assistant_os.mso.human_confirmation import merge_confirmation_into_dict
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]
    assert merged[0]["human_confirmation_status"] == "human_rejected"


def test_execution_allowed_stays_false_after_confirmation():
    entry = _make_queue_entry()
    record_human_confirmation(
        entry_id=entry.queue_entry_id, action_id=entry.prepared_action_id, confirmed=True
    )
    from assistant_os.mso.human_confirmation import merge_confirmation_into_dict
    items = list_pending_confirmable_action_dicts()
    merged = merge_confirmation_into_dict(items[0])
    assert merged["execution_allowed"] is False
    assert merged["can_execute_now"] is False
```

- [ ] **Step 2.2 — Run to confirm tests pass** (these test the merge logic directly without touching the webhook handler yet)

```
pytest tests/test_mso_prepared_actions_confirm_endpoint.py::test_pending_dicts_show_pending_by_default -v
pytest tests/test_mso_prepared_actions_confirm_endpoint.py::test_pending_dicts_reflect_confirmation_after_merge -v
pytest tests/test_mso_prepared_actions_confirm_endpoint.py::test_pending_dicts_reflect_rejection_after_merge -v
pytest tests/test_mso_prepared_actions_confirm_endpoint.py::test_execution_allowed_stays_false_after_confirmation -v
```

Expected: All 4 PASS (the merge logic is tested independently of the HTTP handler).

- [ ] **Step 2.3 — Modify the GET handler in webhook_server.py**

Find `_handle_mso_prepared_actions_pending_get` in `assistant_os/webhook_server.py`. It calls `list_pending_confirmable_action_dicts()`. Add the merge step.

Before the change, the handler body looks roughly like:

```python
items = list_pending_confirmable_action_dicts()
```

After the change:

```python
from assistant_os.mso.human_confirmation import merge_confirmation_into_dict
items = [merge_confirmation_into_dict(i) for i in list_pending_confirmable_action_dicts()]
```

The import should be added at the top of the method or at the module import block (wherever the file's other mso imports live). Follow the existing import style in the file.

- [ ] **Step 2.4 — Run existing prepared-actions tests to confirm no regression**

```
pytest tests/test_confirmable_prepared_action_queue.py -v
pytest tests/test_mso_prepared_actions_confirm_endpoint.py -v
```

Expected: All pass.

- [ ] **Step 2.5 — Commit**

```bash
git add assistant_os/webhook_server.py tests/test_mso_prepared_actions_confirm_endpoint.py
git commit -m "feat(mso): merge human confirmation status into prepared-actions GET response"
```

---

## Task 3: POST /mso/prepared-actions/confirm Endpoint (TDD)

**Files:**
- Modify: `assistant_os/webhook_server.py` — add `_process_mso_confirm_request()` + `_handle_mso_prepared_actions_confirm_post()` + route
- Test: `tests/test_mso_prepared_actions_confirm_endpoint.py` — add endpoint tests

- [ ] **Step 3.1 — Write failing endpoint tests**

Add to `tests/test_mso_prepared_actions_confirm_endpoint.py`:

```python
# ── Endpoint logic tests ─────────────────────────────────────────────────────

from assistant_os.webhook_server import _process_mso_confirm_request


def test_confirm_endpoint_returns_200_on_valid_confirm():
    entry = _make_queue_entry()
    body = json.dumps({
        "entry_id": entry.queue_entry_id,
        "action_id": entry.prepared_action_id,
        "confirmed": True,
        "operator_note": "looks good",
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["ok"] is True
    assert response["human_confirmation_status"] == "human_confirmed"
    assert response["execution_allowed"] is False
    assert response["can_execute_now"] is False


def test_confirm_endpoint_returns_200_on_valid_reject():
    entry = _make_queue_entry()
    body = json.dumps({
        "entry_id": entry.queue_entry_id,
        "action_id": entry.prepared_action_id,
        "confirmed": False,
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["human_confirmation_status"] == "human_rejected"
    assert response["execution_allowed"] is False


def test_confirm_endpoint_writes_to_store():
    entry = _make_queue_entry()
    body = json.dumps({
        "entry_id": entry.queue_entry_id,
        "action_id": entry.prepared_action_id,
        "confirmed": True,
    }).encode()
    _process_mso_confirm_request(body)
    record = get_human_confirmation(entry.queue_entry_id)
    assert record is not None
    assert record.confirmed is True


def test_confirm_endpoint_404_on_unknown_entry():
    body = json.dumps({
        "entry_id": "does-not-exist",
        "action_id": "a1",
        "confirmed": True,
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 404
    assert response["ok"] is False


def test_confirm_endpoint_400_missing_entry_id():
    body = json.dumps({"action_id": "a1", "confirmed": True}).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "entry_id" in response["error"]


def test_confirm_endpoint_400_missing_action_id():
    entry = _make_queue_entry()
    body = json.dumps({"entry_id": entry.queue_entry_id, "confirmed": True}).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "action_id" in response["error"]


def test_confirm_endpoint_400_confirmed_not_bool():
    entry = _make_queue_entry()
    body = json.dumps({
        "entry_id": entry.queue_entry_id,
        "action_id": entry.prepared_action_id,
        "confirmed": "yes",
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 400
    assert "bool" in response["error"]


def test_confirm_endpoint_400_invalid_json():
    status, response = _process_mso_confirm_request(b"not json{{{")
    assert status == 400


def test_confirm_endpoint_execution_allowed_invariant():
    entry = _make_queue_entry()
    body = json.dumps({
        "entry_id": entry.queue_entry_id,
        "action_id": entry.prepared_action_id,
        "confirmed": True,
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response.get("execution_allowed") is False
    assert response.get("can_execute_now") is False
```

- [ ] **Step 3.2 — Run to confirm failure**

```
pytest tests/test_mso_prepared_actions_confirm_endpoint.py -k "endpoint" -v
```

Expected: `ImportError: cannot import name '_process_mso_confirm_request'`

- [ ] **Step 3.3 — Add the module-level function and handler to webhook_server.py**

Find the section in `assistant_os/webhook_server.py` where other module-level handler helpers live (near the existing `_handle_mso_prepared_actions_pending_get` function or after it). Add:

```python
def _process_mso_confirm_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse and validate a confirm request body. Returns (status_code, response_dict).

    Does not grant execution authority. Writes a HumanConfirmationRecord only.
    Execution remains closed: execution_allowed and can_execute_now stay False.
    """
    import json as _json
    from assistant_os.mso.prepared_action_queue import get_confirmable_action_queue_entry
    from assistant_os.mso.human_confirmation import record_human_confirmation

    try:
        data = _json.loads(body_bytes) if body_bytes else {}
    except (_json.JSONDecodeError, Exception):
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = (data.get("entry_id") or "").strip()
    action_id = (data.get("action_id") or "").strip()
    confirmed = data.get("confirmed")
    operator_note = (data.get("operator_note") or "")

    if not entry_id:
        return 400, {"ok": False, "error": "entry_id required"}
    if not action_id:
        return 400, {"ok": False, "error": "action_id required"}
    if not isinstance(confirmed, bool):
        return 400, {"ok": False, "error": "confirmed must be bool (true or false)"}

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": "prepared action not found", "entry_id": entry_id}

    record = record_human_confirmation(
        entry_id=entry_id,
        action_id=action_id,
        confirmed=confirmed,
        operator_note=operator_note,
    )

    return 200, {
        "ok": True,
        "entry_id": entry_id,
        "action_id": action_id,
        "human_confirmation_status": "human_confirmed" if confirmed else "human_rejected",
        "execution_allowed": False,
        "can_execute_now": False,
        "recorded_at": record.recorded_at.isoformat(),
        "note": (
            "Human confirmation recorded. Execution remains closed. "
            "Full authority chain (PolicyDecision → CapabilityToken → OperationBinding "
            "→ AuthorizedPlan → PoliceGate) is still required."
        ),
    }
```

Then add the handler method to the `WebhookHandler` class (place it near `_handle_mso_prepared_actions_pending_get`):

```python
def _handle_mso_prepared_actions_confirm_post(self):
    body = self._read_body()
    status, response = _process_mso_confirm_request(body)
    self._send_json_response(status, response)
```

Then wire it into `do_POST()`. Find the section that routes POST requests (the if/elif chain). Add the new route adjacent to other `/mso/` routes:

```python
elif path == "/mso/prepared-actions/confirm":
    self._handle_mso_prepared_actions_confirm_post()
```

- [ ] **Step 3.4 — Run all endpoint tests**

```
pytest tests/test_mso_prepared_actions_confirm_endpoint.py -v
```

Expected: All tests PASS.

- [ ] **Step 3.5 — Run full test suite to check for regressions**

```
pytest tests/ -x -q
```

Expected: No new failures.

- [ ] **Step 3.6 — Commit**

```bash
git add assistant_os/webhook_server.py tests/test_mso_prepared_actions_confirm_endpoint.py
git commit -m "feat(webhook): add POST /mso/prepared-actions/confirm endpoint"
```

---

## Task 4: Next.js Proxy Route (TypeScript)

**Files:**
- Create: `ui/app/api/mso/prepared-actions/confirm/route.ts`

- [ ] **Step 4.1 — Create the proxy route**

Model it exactly on `ui/app/api/mso/prepared-actions/pending/route.ts` (GET → POST).

```typescript
// ui/app/api/mso/prepared-actions/confirm/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  error: 'Confirm endpoint unavailable',
  execution_allowed: false,
  can_execute_now: false,
}

export async function POST(req: NextRequest) {
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ ok: false, error: 'Invalid JSON body' }, { status: 400 })
  }

  const url = `${getWebhookBaseUrl()}/mso/prepared-actions/confirm`

  let upstreamRes: Response
  try {
    upstreamRes = await fetch(url, {
      method: 'POST',
      headers: { ...getWebhookHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(4000),
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { ...UNAVAILABLE_RESPONSE, error: `Confirm backend unavailable: ${message}` },
      { status: 502 },
    )
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      { ...UNAVAILABLE_RESPONSE, error: `Confirm backend returned non-JSON (${upstreamRes.status})` },
      { status: 502 },
    )
  }

  return NextResponse.json(payload, { status: upstreamRes.status })
}
```

- [ ] **Step 4.2 — Verify TypeScript compiles**

```
cd ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4.3 — Commit**

```bash
git add ui/app/api/mso/prepared-actions/confirm/route.ts
git commit -m "feat(ui): add Next.js proxy for POST /mso/prepared-actions/confirm"
```

---

## Task 5: API Function and Types (TypeScript)

**Files:**
- Modify: `ui/lib/types.ts`
- Modify: `ui/lib/sovereign/api.ts`

- [ ] **Step 5.1 — Add types to ui/lib/types.ts**

Add these two interfaces after the `PreparedActionsQueueResponse` block (around line 589):

```typescript
// ── Human confirmation (S-HUMAN-CONFIRM-01) ───────────────────────────────

export interface ConfirmPreparedActionPayload {
  entry_id: string
  action_id: string
  confirmed: boolean
  operator_note?: string
}

export interface ConfirmPreparedActionResult {
  ok: boolean
  entry_id?: string
  action_id?: string
  human_confirmation_status?: 'human_confirmed' | 'human_rejected'
  execution_allowed: false
  can_execute_now: false
  recorded_at?: string
  note?: string
  error?: string
}
```

Also extend `PreparedActionQueueEntry` with two optional fields (add after `notes: string`):

```typescript
  confirmation_recorded_at?: string
  operator_note?: string
```

- [ ] **Step 5.2 — Add confirmPreparedAction() to ui/lib/sovereign/api.ts**

Add after `sendMSOConfirmation()`:

```typescript
/**
 * Record a human confirmation signal for a prepared action.
 * Does not grant execution authority or satisfy any authority chain step.
 */
export async function confirmPreparedAction(
  entryId: string,
  actionId: string,
  confirmed: boolean,
  operatorNote?: string,
): Promise<ConfirmPreparedActionResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_id: entryId,
        action_id: actionId,
        confirmed,
        operator_note: operatorNote ?? '',
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      human_confirmation_status: data.human_confirmation_status,
      execution_allowed: false,
      can_execute_now: false,
      recorded_at: data.recorded_at,
      note: data.note,
    }
  } catch (err) {
    return {
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: err instanceof Error ? err.message : 'Network error',
    }
  }
}
```

Add the import for the new types at the top of `api.ts` (extend the existing import from `./types`):

```typescript
import type {
  SovereignChatRequest,
  SovereignChatResponse,
  SurfaceType,
  ExecutionStatus,
  ExecutionStatusSource,
  ConfirmPreparedActionResult,
} from './types'
```

- [ ] **Step 5.3 — Verify TypeScript compiles**

```
cd ui && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5.4 — Commit**

```bash
git add ui/lib/types.ts ui/lib/sovereign/api.ts
git commit -m "feat(ui): add confirmPreparedAction API function and types"
```

---

## Task 6: Confirm/Reject Buttons in PreparedActionDetailPanel (UI)

**Files:**
- Modify: `ui/components/sovereign/PreparedActionDetailPanel.tsx`

- [ ] **Step 6.1 — Add local state and confirm handler**

Replace the opening of `PreparedActionDetailPanel` component with:

```typescript
'use client'

import { useState } from 'react'
import type { PreparedActionQueueEntry } from '@/lib/types'
import { AuthorityTimeline } from './AuthorityTimeline'
import { PreparedActionInputTrace } from './PreparedActionInputTrace'
import { confirmPreparedAction } from '@/lib/sovereign/api'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'
```

Then inside `PreparedActionDetailPanel`, before the return statement, add:

```typescript
  const [confirmStatus, setConfirmStatus] = useState<string | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const refresh = usePreparedActionsStore((s) => s.refresh)

  async function handleConfirm(confirmed: boolean) {
    setIsConfirming(true)
    setConfirmError(null)
    const result = await confirmPreparedAction(
      item.queue_entry_id,
      item.prepared_action_id,
      confirmed,
    )
    setIsConfirming(false)
    if (result.ok && result.human_confirmation_status) {
      setConfirmStatus(result.human_confirmation_status)
      if (typeof refresh === 'function') refresh()
    } else {
      setConfirmError(result.error ?? 'Confirmation failed')
    }
  }
```

- [ ] **Step 6.2 — Add the Human Review Action section to the JSX**

In the return statement, after the existing "Next Safe Step" div (around line 104), add:

```tsx
      {/* I. Human Review Action */}
      <div className="mt-3 pt-2 border-t border-os-border/60">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-2">
          Human Review Action
        </p>

        {confirmStatus !== null ? (
          <p className={`text-[10px] font-mono ${
            confirmStatus === 'human_confirmed' ? 'text-ok' : 'text-warn'
          }`}>
            {confirmStatus === 'human_confirmed' ? 'Review confirmed.' : 'Rejected.'}{' '}
            Execution remains closed.
          </p>
        ) : item.human_confirmation_status !== 'pending' ? (
          <p className="text-[10px] font-mono text-tx-muted">
            Human review: {item.human_confirmation_status}
          </p>
        ) : (
          <>
            <p className="text-[10px] font-mono text-tx-muted mb-3 leading-relaxed">
              Confirming review does not execute, grant tokens, or call PoliceGate.
              Execution remains closed until the full authority chain is satisfied.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => handleConfirm(true)}
                disabled={isConfirming}
                className="px-3 py-1.5 text-[10px] font-mono bg-ok/10 text-ok border border-ok/30 rounded hover:bg-ok/20 disabled:opacity-50 cursor-default"
              >
                {isConfirming ? 'Recording…' : 'Confirm Review'}
              </button>
              <button
                onClick={() => handleConfirm(false)}
                disabled={isConfirming}
                className="px-3 py-1.5 text-[10px] font-mono bg-warn/10 text-warn border border-warn/30 rounded hover:bg-warn/20 disabled:opacity-50 cursor-default"
              >
                Reject
              </button>
            </div>
            {confirmError && (
              <p className="text-[10px] font-mono text-warn mt-2">{confirmError}</p>
            )}
          </>
        )}
      </div>
```

- [ ] **Step 6.3 — Verify TypeScript compiles**

```
cd ui && npx tsc --noEmit
```

Expected: No errors. If `usePreparedActionsStore` doesn't expose a `refresh` action, check the store definition and use whatever refresh/poll trigger it provides (e.g., call `fetchPreparedActions()` directly if that's what the store exposes). Do not invent a store method — read the store first.

- [ ] **Step 6.4 — Check if usePreparedActionsStore exposes refresh**

Read `ui/stores/prepared-actions-store.ts` to confirm the refresh API. If the store exposes a different name (e.g., `fetchNow`, `triggerPoll`), use that name instead. If no refresh action exists, skip the `refresh()` call — the next poll cycle will pick up the updated status automatically.

- [ ] **Step 6.5 — Commit**

```bash
git add ui/components/sovereign/PreparedActionDetailPanel.tsx
git commit -m "feat(ui): add Confirm/Reject buttons to PreparedActionDetailPanel"
```

---

## Task 7: Integration Smoke Test

**Files:**
- Test: `tests/test_mso_prepared_actions_confirm_endpoint.py` — add end-to-end flow test

- [ ] **Step 7.1 — Add end-to-end flow test**

Add to `tests/test_mso_prepared_actions_confirm_endpoint.py`:

```python
# ── End-to-end flow test ─────────────────────────────────────────────────────

def test_full_flow_plan_request_to_confirmation():
    """
    Verify the complete segment: enqueue → GET pending → confirm → GET pending shows updated status.
    Execution must remain closed at every step.
    """
    from assistant_os.mso.human_confirmation import merge_confirmation_into_dict

    # 1. MSO produces a prepared action (simulating 05.1 flow)
    entry = _make_queue_entry("create architecture doc for auth module")
    entry_id = entry.queue_entry_id
    action_id = entry.prepared_action_id

    # 2. GET pending — visible in Mission Control
    items = list_pending_confirmable_action_dicts()
    assert len(items) == 1
    assert items[0]["human_confirmation_status"] == "pending"
    assert items[0]["execution_allowed"] is False

    # 3. Operator confirms via endpoint
    body = json.dumps({
        "entry_id": entry_id,
        "action_id": action_id,
        "confirmed": True,
        "operator_note": "architecture doc plan looks correct",
    }).encode()
    status, response = _process_mso_confirm_request(body)
    assert status == 200
    assert response["ok"] is True
    assert response["execution_allowed"] is False
    assert response["can_execute_now"] is False

    # 4. GET pending — status updated after merge
    items = list_pending_confirmable_action_dicts()
    merged = [merge_confirmation_into_dict(i) for i in items]
    assert merged[0]["human_confirmation_status"] == "human_confirmed"
    assert merged[0]["execution_allowed"] is False
    assert merged[0]["can_execute_now"] is False

    # 5. Confirmation record exists in store
    record = get_human_confirmation(entry_id)
    assert record is not None
    assert record.confirmed is True
    assert record.execution_allowed is False
```

- [ ] **Step 7.2 — Run full test**

```
pytest tests/test_mso_prepared_actions_confirm_endpoint.py -v
```

Expected: All tests PASS.

- [ ] **Step 7.3 — Run full suite**

```
pytest tests/ -x -q
```

Expected: No new failures.

- [ ] **Step 7.4 — Commit**

```bash
git add tests/test_mso_prepared_actions_confirm_endpoint.py
git commit -m "test(mso): add end-to-end flow test for prepared action confirmation"
```

---

## Acceptance Criteria

- [ ] A prepared action created by 05.1 is visible in Mission Control (already true; must not regress)
- [ ] Operator can expand a prepared action in `PreparedActionDetailPanel` and see Confirm / Reject buttons
- [ ] Clicking Confirm writes a `HumanConfirmationRecord` with `execution_allowed=False`
- [ ] The prepared-actions queue view refreshes and shows `human_confirmation_status: human_confirmed` or `human_rejected`
- [ ] Clicking Reject works identically with `confirmed=False`
- [ ] `execution_allowed` is `False` on every artifact, at every step, confirmed by tests
- [ ] `can_execute_now` is `False` everywhere
- [ ] No authority chain step (PolicyDecision, CapabilityToken, OperationBinding, AuthorizedPlan, PoliceGate) is satisfied or called
- [ ] All new Python tests pass: `pytest tests/test_human_confirmation.py tests/test_mso_prepared_actions_confirm_endpoint.py -v`
- [ ] Full test suite passes with no regressions: `pytest tests/ -x -q`
- [ ] `cd ui && npx tsc --noEmit` passes

---

## Out of Scope (Future Sprints)

| Item | Sprint |
|------|--------|
| PolicyDecision adapter after confirmation | 05.3 |
| CapabilityToken issuance | 05.4+ |
| OperationBinding | 05.4+ |
| AuthorizedPlan creation | 05.4+ |
| Police Gate execution bridge | 05.5+ |
| Runner / pipeline invocation | 05.5+ |
| Outcome interpretation by MSO | 05.6+ |
| Visual Operation Trace | Future |
| Advanced Mode, provider selector, local Llama | Not planned |
| Persistent (DB-backed) confirmation store | Future (currently in-memory) |

---

## Risk Register

| Risk | Mitigation |
|------|------------|
| `usePreparedActionsStore` may not expose `refresh` | Step 6.4 reads the store before use; fall back to next poll cycle |
| `do_POST()` routing conflict with existing `/mso/` paths | Add the route in the same if/elif block; grep existing routes first |
| `list_pending_confirmable_action_dicts()` dict key may be `entry_id` not `queue_entry_id` | `merge_confirmation_into_dict` checks both keys |
| In-memory store resets on server restart | Accepted for this sprint; persistence is out of scope |
| TypeScript import path for `ConfirmPreparedActionResult` | Added to `@/lib/types` where `PreparedActionQueueEntry` already lives |
