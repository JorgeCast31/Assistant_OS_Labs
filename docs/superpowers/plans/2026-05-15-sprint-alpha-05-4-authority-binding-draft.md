# SPRINT-ALPHA-05.4 — CapabilityToken / OperationBinding Draft Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge an approved `MSOPolicyDecisionDraft` into a new `MSOAuthorityBindingDraft` artifact — the next authority chain stage — without issuing production tokens, creating AuthorizedPlan, calling PoliceGate, or executing.

**Architecture:** Create `assistant_os/mso/authority_binding.py` with a `MSOAuthorityBindingDraft` frozen dataclass (identical invariant pattern to `MSOPolicyDecisionDraft`). The draft advances the chain label only — it does not touch the production `CapabilityToken`/`OperationBinding`/`AuthorizedPlan`/`PoliceGate`/`RunnerAPI` primitives, which all carry real side effects (token registry, HMAC signing, single-use consumption, code execution). Wire it through a new backend endpoint, Next.js proxy, updated types, API helper, and `PreparedActionConfirmSurface` badge.

**Tech Stack:** Python 3.11 frozen dataclasses, threading.Lock, pytest — Next.js 14 App Router, TypeScript, React `useState`

---

## Primitive Inspection Summary (pre-plan)

| Primitive | Location | Status | Safe for 05.4? |
|-----------|----------|--------|----------------|
| `CapabilityToken` | `capabilities/token_models.py` | Production — registers in `_token_registry` | NO — `issue_token()` is non-idempotent |
| `OperationBinding` | `capabilities/token_models.py` | Production binding data struct | NO — bound to `issue_token()` flow |
| `AuthorizedPlan` | `sandbox/authorized_plan.py` | Production — HMAC-signed, requires authority artifact | NO |
| `AuthorityArtifact` | `authority/artifact.py` | Production — HMAC-SHA256 signing | NO |
| `PoliceGate.check()` | `police/enforcement.py` | Production enforcement — marks token SPENT | NO |
| `RunnerAPI.execute()` | `sandbox/runner_api.py` | Production dispatch — actual execution | NO |
| `check_capability()` | `mso/capability_registry.py` | Read-only query — no side effects | Already used in 05.3 |

**Decision:** Create `MSOAuthorityBindingDraft` as a new draft artifact. Does not call any production primitive above. Follows the exact pattern of `MSOPolicyDecisionDraft`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `assistant_os/mso/authority_binding.py` | CREATE | `MSOAuthorityBindingDraft` dataclass, in-memory store, `create_mso_authority_binding()`, `merge_authority_binding_into_dict()` |
| `tests/test_mso_authority_binding.py` | CREATE | 34 tests across 5 classes |
| `assistant_os/webhook_server.py` | MODIFY | `_process_mso_authority_binding_request()` function, `_handle_mso_prepared_actions_authority_binding_post()` method, route in `do_POST()`, merge chain in GET pending |
| `ui/app/api/mso/prepared-actions/authority-binding/route.ts` | CREATE | Next.js proxy route |
| `ui/lib/types.ts` | MODIFY | Add optional authority binding fields to `PreparedActionQueueEntry`; add `MSOAuthorityBindingResult` interface |
| `ui/lib/sovereign/api.ts` | MODIFY | Add `requestMSOAuthorityBinding()` |
| `ui/components/sovereign/PreparedActionConfirmSurface.tsx` | MODIFY | Auto-trigger authority binding after approved policy review; show badge |

---

## Task 1: Create MSOAuthorityBindingDraft module (TDD)

**Files:**
- Create: `assistant_os/mso/authority_binding.py`
- Create: `tests/test_mso_authority_binding.py`

### Step 1.1: Write the failing tests (invariants + core logic)

```python
# tests/test_mso_authority_binding.py
"""Tests for MSOAuthorityBindingDraft and create_mso_authority_binding."""
from __future__ import annotations

import pytest

from assistant_os.mso.authority_binding import (
    MSOAuthorityBindingDraft,
    clear_mso_authority_binding_store_for_tests,
    create_mso_authority_binding,
    get_mso_authority_binding,
    merge_authority_binding_into_dict,
)
from assistant_os.mso.policy_review import (
    clear_mso_policy_review_store_for_tests,
    evaluate_mso_policy_for_prepared_action,
)
from assistant_os.mso.human_confirmation import (
    clear_human_confirmation_store_for_tests,
    record_human_confirmation,
)
from assistant_os.mso.prepared_action_queue import (
    clear_confirmable_action_queue_for_tests,
    enqueue_confirmable_prepared_action,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queue_entry(*, action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
    from assistant_os.mso.execution_proposal import build_execution_proposal
    from assistant_os.mso.authority_preparation import prepare_authority_from_proposal
    from assistant_os.mso.confirmable_prepared_action import build_confirmable_from_preparation
    proposal = build_execution_proposal(
        user_intent="test intent", domain=domain,
        requested_action=action, capability_name=capability_name,
    )
    preparation = prepare_authority_from_proposal(proposal)
    confirmable = build_confirmable_from_preparation(preparation)
    return enqueue_confirmable_prepared_action(confirmable)


def _make_policy_review(entry, *, confirmed=True):
    confirmation = record_human_confirmation(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        confirmed=confirmed,
    )
    return evaluate_mso_policy_for_prepared_action(entry, confirmation)


def _make_approved_pair(action="CODE_REVIEW", domain="CODE", capability_name="code_review"):
    """Return (entry, policy_review) where policy_review.policy_outcome is approved."""
    entry = _make_queue_entry(action=action, domain=domain, capability_name=capability_name)
    review = _make_policy_review(entry)
    return entry, review


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingDraftInvariants:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_execution_allowed_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="execution_allowed"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                execution_allowed=True,
            )

    def test_can_execute_now_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="can_execute_now"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                can_execute_now=True,
            )

    def test_used_execution_invariant_raises_on_true(self):
        with pytest.raises(ValueError, match="used_execution"):
            MSOAuthorityBindingDraft(
                authority_binding_id="ab-test",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
                used_execution=True,
            )

    def test_authority_binding_id_must_be_non_empty(self):
        with pytest.raises(ValueError, match="authority_binding_id"):
            MSOAuthorityBindingDraft(
                authority_binding_id="",
                entry_id="e1",
                action_id="a1",
                policy_review_id="prd-1",
            )

    def test_binding_status_defaults_to_drafted(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.binding_status == "drafted"

    def test_requires_authorized_plan_defaults_to_true(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.requires_authorized_plan is True

    def test_requires_police_gate_defaults_to_true(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.requires_police_gate is True

    def test_artifact_type_is_mso_authority_binding_draft(self):
        b = MSOAuthorityBindingDraft(
            authority_binding_id="ab-x",
            entry_id="e1",
            action_id="a1",
            policy_review_id="prd-1",
        )
        assert b.artifact_type == "mso_authority_binding_draft"


# ---------------------------------------------------------------------------
# Core logic tests
# ---------------------------------------------------------------------------

class TestCreateMSOAuthorityBinding:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_approved_creates_binding(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.authority_binding_id.startswith("ab-")
        assert binding.policy_review_id == review.policy_review_id
        assert binding.entry_id == entry.queue_entry_id

    def test_approved_confirm_only_creates_binding(self):
        # WORK_CREATE is confirm_only in the capability registry
        entry, review = _make_approved_pair(
            action="WORK_CREATE", domain="WORK", capability_name="work_create"
        )
        assert review.policy_outcome in ("approved", "approved_confirm_only")
        binding = create_mso_authority_binding(entry, review)
        assert binding.authority_binding_id.startswith("ab-")

    def test_denied_raises_value_error(self):
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        review = _make_policy_review(entry)
        assert review.policy_outcome == "denied"
        with pytest.raises(ValueError, match="denied"):
            create_mso_authority_binding(entry, review)

    def test_entry_id_mismatch_raises(self):
        entry1, review1 = _make_approved_pair()
        entry2 = _make_queue_entry()
        # Swap: pass entry2 with review1
        with pytest.raises(ValueError, match="entry_id mismatch"):
            create_mso_authority_binding(entry2, review1)

    def test_idempotent_same_id_on_duplicate_call(self):
        entry, review = _make_approved_pair()
        b1 = create_mso_authority_binding(entry, review)
        b2 = create_mso_authority_binding(entry, review)
        assert b1.authority_binding_id == b2.authority_binding_id

    def test_execution_always_false(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.execution_allowed is False
        assert binding.can_execute_now is False
        assert binding.used_execution is False

    def test_requires_authorized_plan_and_police_gate_always_true(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.requires_authorized_plan is True
        assert binding.requires_police_gate is True

    def test_binding_status_is_drafted(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        assert binding.binding_status == "drafted"


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingStore:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_store_persists_binding(self):
        entry, review = _make_approved_pair()
        binding = create_mso_authority_binding(entry, review)
        retrieved = get_mso_authority_binding(entry.queue_entry_id)
        assert retrieved is not None
        assert retrieved.authority_binding_id == binding.authority_binding_id

    def test_retrieve_returns_none_for_unknown(self):
        assert get_mso_authority_binding("no-such-entry") is None

    def test_clear_empties_store(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        clear_mso_authority_binding_store_for_tests()
        assert get_mso_authority_binding(entry.queue_entry_id) is None

    def test_idempotency_does_not_overwrite_store(self):
        entry, review = _make_approved_pair()
        b1 = create_mso_authority_binding(entry, review)
        b2 = create_mso_authority_binding(entry, review)
        stored = get_mso_authority_binding(entry.queue_entry_id)
        assert stored.authority_binding_id == b1.authority_binding_id == b2.authority_binding_id


# ---------------------------------------------------------------------------
# Merge into read model tests
# ---------------------------------------------------------------------------

class TestMergeAuthorityBindingIntoDict:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_merge_overlays_authority_binding_fields(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert "authority_binding_id" in merged
        assert "authority_binding_status" in merged
        assert "authority_binding_created_at" in merged
        assert "requires_authorized_plan" in merged
        assert "requires_police_gate" in merged

    def test_merge_preserves_original_fields(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {"queue_entry_id": entry.queue_entry_id, "domain": "CODE", "extra": "keep"}
        merged = merge_authority_binding_into_dict(item)
        assert merged["domain"] == "CODE"
        assert merged["extra"] == "keep"

    def test_merge_noop_when_no_binding_exists(self):
        item = {"queue_entry_id": "no-such-entry", "domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert merged == item

    def test_merge_execution_fields_unchanged(self):
        entry, review = _make_approved_pair()
        create_mso_authority_binding(entry, review)
        item = {
            "queue_entry_id": entry.queue_entry_id,
            "execution_allowed": False,
            "can_execute_now": False,
        }
        merged = merge_authority_binding_into_dict(item)
        assert merged["execution_allowed"] is False
        assert merged["can_execute_now"] is False

    def test_merge_noop_when_no_queue_entry_id(self):
        item = {"domain": "CODE"}
        merged = merge_authority_binding_into_dict(item)
        assert merged == item


# ---------------------------------------------------------------------------
# Endpoint logic tests
# ---------------------------------------------------------------------------

class TestMSOAuthorityBindingEndpoint:
    def setup_method(self):
        clear_mso_authority_binding_store_for_tests()
        clear_mso_policy_review_store_for_tests()
        clear_human_confirmation_store_for_tests()
        clear_confirmable_action_queue_for_tests()

    def test_missing_entry_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"action_id": "a1"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_missing_action_id_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"entry_id": "e1"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_unknown_entry_returns_404(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        body = json.dumps({"entry_id": "no-such", "action_id": "no-action"}).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 404
        assert data["ok"] is False

    def test_action_id_mismatch_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": "wrong-action-id",
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 400
        assert data["ok"] is False

    def test_no_policy_review_returns_422(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry = _make_queue_entry()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 422
        assert "policy_review_required" in data.get("error", "")

    def test_denied_policy_review_returns_422(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry = _make_queue_entry(action="ACTION_UNKNOWN", domain="UNKNOWN", capability_name="")
        _make_policy_review(entry)
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 422
        assert "policy_denied" in data.get("error", "")

    def test_approved_returns_200_with_binding_id(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 200
        assert data["ok"] is True
        assert data["authority_binding_id"].startswith("ab-")

    def test_approved_confirm_only_returns_200(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair(
            action="WORK_CREATE", domain="WORK", capability_name="work_create"
        )
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        status, data = _process_mso_authority_binding_request(body)
        assert status == 200
        assert data["ok"] is True

    def test_success_requires_authorized_plan_true(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["requires_authorized_plan"] is True

    def test_success_requires_police_gate_true(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["requires_police_gate"] is True

    def test_success_execution_always_closed(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert data["execution_allowed"] is False
        assert data["can_execute_now"] is False
        assert data["used_execution"] is False

    def test_duplicate_post_returns_same_binding_id(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data1 = _process_mso_authority_binding_request(body)
        _, data2 = _process_mso_authority_binding_request(body)
        assert data1["authority_binding_id"] == data2["authority_binding_id"]

    def test_invalid_json_returns_400(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        status, data = _process_mso_authority_binding_request(b"not-json")
        assert status == 400
        assert data["ok"] is False

    def test_no_authorized_plan_field_in_response(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert "authorized_plan" not in data
        assert "authorized_plan_id" not in data

    def test_no_runner_field_in_response(self):
        from assistant_os.webhook_server import _process_mso_authority_binding_request
        import json
        entry, review = _make_approved_pair()
        body = json.dumps({
            "entry_id": entry.queue_entry_id,
            "action_id": entry.prepared_action_id,
        }).encode()
        _, data = _process_mso_authority_binding_request(body)
        assert "runner" not in data
        assert "execution_id" not in data
```

- [ ] **Step 1.1: Run the tests — verify they all fail (ImportError on authority_binding)**

```
python -m pytest tests/test_mso_authority_binding.py -v --tb=short
```
Expected: ImportError or ModuleNotFoundError on `assistant_os.mso.authority_binding`

- [ ] **Step 1.2: Write the implementation**

Create `assistant_os/mso/authority_binding.py`:

```python
"""MSO AuthorityBindingDraft — second authority chain artifact after MSOPolicyDecisionDraft.

This module produces a deterministic, frozen ``MSOAuthorityBindingDraft`` from an
approved ``MSOPolicyDecisionDraft``. It advances the chain label only.

Authority chain position
------------------------
MSOExecutionProposal
→ AuthorityPreparationRequest
→ ConfirmablePreparedAction / queue
→ HumanConfirmationRecord
→ MSOPolicyDecisionDraft
→ MSOAuthorityBindingDraft                                            ← this module
→ [CapabilityToken]   (future — production token_issuer.issue_token)
→ [OperationBinding]  (future — production token_models.OperationBinding)
→ [AuthorizedPlan]    (future)
→ [PoliceGate]        (future)
→ [execution]         (future)

Design
------
This module is intentionally NOT:
  - calling token_issuer.issue_token() (non-idempotent, registers in _token_registry)
  - creating OperationBinding or AuthorizedPlan (production artifacts)
  - calling PoliceGate enforcement.check() (marks tokens SPENT)
  - calling RunnerAPI.execute() (actual execution)
  - signing with AuthorityArtifact (HMAC-SHA256, production)

This IS:
  - a draft artifact for the MSO authority chain (chain position 6)
  - derived from an approved MSOPolicyDecisionDraft
  - idempotent by entry_id (duplicate calls return same artifact)
  - always execution_allowed=False, can_execute_now=False, used_execution=False
  - stored in process-local in-memory store keyed by entry_id
  - merged into GET /mso/prepared-actions/pending read model at read time

Invariants (enforced by __post_init__)
--------------------------------------
  execution_allowed     = False  (always)
  can_execute_now       = False  (always)
  used_execution        = False  (always)
  authority_binding_id != ""     (always non-empty)

Fail-closed rules
-----------------
- policy_outcome not in ("approved", "approved_confirm_only") → rejected
- entry_id mismatch between entry and policy_review → rejected
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional
from uuid import uuid4

from .policy_review import MSOPolicyDecisionDraft
from .prepared_action_queue import ConfirmablePreparedActionQueueEntry


def _new_id() -> str:
    return f"ab-{uuid4()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class MSOAuthorityBindingDraft:
    """Frozen MSO-scope authority binding draft.

    Second authority chain artifact after MSOPolicyDecisionDraft.
    Produced by create_mso_authority_binding().

    Never calls token_issuer, creates OperationBinding/AuthorizedPlan,
    calls PoliceGate, or executes.
    execution_allowed, can_execute_now, and used_execution are invariantly False.
    """

    # Identity
    authority_binding_id: str = field(default_factory=_new_id)
    entry_id: str = ""
    action_id: str = ""
    policy_review_id: str = ""

    # Source context
    domain: str = "UNKNOWN"
    requested_action: str = ""
    capability_name: str = ""
    capability_mode: str = ""
    policy_outcome: str = ""

    # Binding state
    binding_status: str = "drafted"

    # Chain requirements — always True at this stage
    requires_authorized_plan: bool = True
    requires_police_gate: bool = True

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    can_execute_now: bool = False
    used_execution: bool = False

    # Timestamps and notes
    created_at: datetime = field(default_factory=_now)
    notes: str = ""

    # Artifact type tag
    artifact_type: str = "mso_authority_binding_draft"

    def __post_init__(self) -> None:
        if self.execution_allowed is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.execution_allowed must always be False. "
                "An authority binding draft does not authorize execution."
            )
        if self.can_execute_now is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.can_execute_now must always be False. "
                "An authority binding draft does not open any execution path."
            )
        if self.used_execution is not False:
            raise ValueError(
                "MSOAuthorityBindingDraft.used_execution must always be False. "
                "No execution was performed to produce an authority binding draft."
            )
        if not self.authority_binding_id:
            raise ValueError(
                "MSOAuthorityBindingDraft.authority_binding_id must be non-empty."
            )

    def to_dict(self) -> dict:
        return {
            "artifact_type": self.artifact_type,
            "authority_binding_id": self.authority_binding_id,
            "entry_id": self.entry_id,
            "action_id": self.action_id,
            "policy_review_id": self.policy_review_id,
            "domain": self.domain,
            "requested_action": self.requested_action,
            "capability_name": self.capability_name,
            "capability_mode": self.capability_mode,
            "policy_outcome": self.policy_outcome,
            "binding_status": self.binding_status,
            "requires_authorized_plan": self.requires_authorized_plan,
            "requires_police_gate": self.requires_police_gate,
            "execution_allowed": self.execution_allowed,
            "can_execute_now": self.can_execute_now,
            "used_execution": self.used_execution,
            "created_at": self.created_at.isoformat(),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_store: dict[str, MSOAuthorityBindingDraft] = {}
_lock = Lock()


def _store_authority_binding(binding: MSOAuthorityBindingDraft) -> None:
    with _lock:
        _store[binding.entry_id] = binding


def get_mso_authority_binding(entry_id: str) -> Optional[MSOAuthorityBindingDraft]:
    """Return the stored MSOAuthorityBindingDraft for entry_id, or None."""
    with _lock:
        return _store.get(entry_id)


def clear_mso_authority_binding_store_for_tests() -> None:
    """Empty the store. FOR TESTS ONLY."""
    with _lock:
        _store.clear()


# ---------------------------------------------------------------------------
# Merge into GET read model
# ---------------------------------------------------------------------------

def merge_authority_binding_into_dict(item_dict: dict) -> dict:
    """Overlay authority binding fields onto a prepared action dict (by queue_entry_id).

    Pure read — never mutates the store or the source dict.
    Returns a new dict with authority_binding_id, authority_binding_status,
    authority_binding_created_at, requires_authorized_plan, and requires_police_gate
    overlaid if a binding record exists.
    """
    entry_id = item_dict.get("queue_entry_id", "")
    if not entry_id:
        return item_dict
    binding = get_mso_authority_binding(entry_id)
    if binding is None:
        return item_dict
    result = dict(item_dict)
    result["authority_binding_id"] = binding.authority_binding_id
    result["authority_binding_status"] = binding.binding_status
    result["authority_binding_created_at"] = binding.created_at.isoformat()
    result["requires_authorized_plan"] = binding.requires_authorized_plan
    result["requires_police_gate"] = binding.requires_police_gate
    return result


# ---------------------------------------------------------------------------
# Core creation function
# ---------------------------------------------------------------------------

def create_mso_authority_binding(
    entry: ConfirmablePreparedActionQueueEntry,
    policy_review: MSOPolicyDecisionDraft,
) -> MSOAuthorityBindingDraft:
    """Create an MSOAuthorityBindingDraft from an approved MSOPolicyDecisionDraft.

    Idempotent: same entry_id → same authority_binding_id.
    Does NOT call token_issuer, create OperationBinding/AuthorizedPlan,
    call PoliceGate, or invoke runner.

    Parameters
    ----------
    entry : ConfirmablePreparedActionQueueEntry
    policy_review : MSOPolicyDecisionDraft
        Must have policy_outcome in ("approved", "approved_confirm_only").

    Returns
    -------
    MSOAuthorityBindingDraft
        Frozen artifact stored in the authority binding store.

    Raises
    ------
    ValueError
        If policy_outcome is not approved or approved_confirm_only.
        If entry_id does not match policy_review.entry_id.
    """
    existing = get_mso_authority_binding(entry.queue_entry_id)
    if existing is not None:
        return existing

    if policy_review.policy_outcome not in ("approved", "approved_confirm_only"):
        raise ValueError(
            f"Cannot create authority binding for policy_outcome={policy_review.policy_outcome!r}. "
            "Only 'approved' or 'approved_confirm_only' outcomes may advance the authority chain. "
            "Denied outcomes do not advance."
        )

    if policy_review.entry_id != entry.queue_entry_id:
        raise ValueError(
            f"entry_id mismatch: policy_review.entry_id={policy_review.entry_id!r} "
            f"does not match entry.queue_entry_id={entry.queue_entry_id!r}. "
            "Authority binding rejected to prevent cross-entry authority confusion."
        )

    binding = MSOAuthorityBindingDraft(
        entry_id=entry.queue_entry_id,
        action_id=entry.prepared_action_id,
        policy_review_id=policy_review.policy_review_id,
        domain=entry.domain,
        requested_action=entry.requested_action,
        capability_name=entry.capability_name or policy_review.capability_name,
        capability_mode=policy_review.capability_mode,
        policy_outcome=policy_review.policy_outcome,
        binding_status="drafted",
        requires_authorized_plan=True,
        requires_police_gate=True,
        execution_allowed=False,
        can_execute_now=False,
        used_execution=False,
        notes=(
            f"Authority binding draft for entry '{entry.queue_entry_id}'. "
            f"Policy review '{policy_review.policy_review_id}' "
            f"outcome={policy_review.policy_outcome!r}. "
            "AuthorizedPlan, PoliceGate, and execution still required."
        ),
    )
    _store_authority_binding(binding)
    return binding
```

- [ ] **Step 1.3: Run tests — verify all pass**

```
python -m pytest tests/test_mso_authority_binding.py -v --tb=short
```
Expected: all tests pass (endpoint tests will fail at import — that's Task 2)

- [ ] **Step 1.4: Commit**

```bash
git add assistant_os/mso/authority_binding.py tests/test_mso_authority_binding.py
git commit -m "feat(mso): add MSOAuthorityBindingDraft module (Task 1) — 05.4"
```

---

## Task 2: Add POST /mso/prepared-actions/authority-binding endpoint

**Files:**
- Modify: `assistant_os/webhook_server.py`

Three changes needed:
1. Add `_process_mso_authority_binding_request()` module-level function (near line 556, after `_process_mso_policy_review_request`)
2. Add `_handle_mso_prepared_actions_authority_binding_post()` handler method (after `_handle_mso_prepared_actions_policy_review_post`, around line 4905)
3. Add route in `do_POST()` (after the policy-review route, around line 1621)
4. Update `_handle_mso_prepared_actions_pending_get()` merge chain

- [ ] **Step 2.1: Add the module-level processor function**

Insert immediately after the closing of `_process_mso_policy_review_request` (after line 555, before `_wrap_work_result`):

```python
def _process_mso_authority_binding_request(body_bytes: bytes) -> tuple[int, dict]:
    """Parse, validate, and create an MSOAuthorityBindingDraft for an approved prepared action.

    Returns (status_code, response_dict).

    Does NOT: call token_issuer.issue_token(), create OperationBinding/AuthorizedPlan,
    call PoliceGate enforcement.check(), invoke RunnerAPI.execute(), or change
    execution_allowed. execution_allowed, can_execute_now, and used_execution remain False always.
    """
    import json as _json

    try:
        data = _json.loads(body_bytes) if body_bytes else {}
    except Exception:  # noqa: BLE001
        return 400, {"ok": False, "error": "Invalid JSON body"}

    entry_id = (data.get("entry_id") or "").strip()
    action_id = (data.get("action_id") or "").strip()

    if not entry_id or not action_id:
        return 400, {"ok": False, "error": "entry_id and action_id are required"}

    from .mso.prepared_action_queue import get_confirmable_action_queue_entry
    from .mso.policy_review import get_mso_policy_review
    from .mso.authority_binding import create_mso_authority_binding

    entry = get_confirmable_action_queue_entry(entry_id)
    if entry is None:
        return 404, {"ok": False, "error": f"Queue entry not found: {entry_id!r}"}

    if entry.prepared_action_id != action_id:
        return 400, {
            "ok": False,
            "error": (
                f"action_id mismatch: entry has action_id={entry.prepared_action_id!r}, "
                f"request has action_id={action_id!r}"
            ),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    policy_review = get_mso_policy_review(entry_id)
    if policy_review is None:
        return 422, {
            "ok": False,
            "error": "policy_review_required: no policy review recorded for this entry",
            "execution_allowed": False,
            "can_execute_now": False,
        }

    if policy_review.policy_outcome not in ("approved", "approved_confirm_only"):
        return 422, {
            "ok": False,
            "error": (
                f"policy_denied: policy_outcome={policy_review.policy_outcome!r} "
                "does not permit authority binding"
            ),
            "execution_allowed": False,
            "can_execute_now": False,
            "policy_outcome": policy_review.policy_outcome,
        }

    try:
        binding = create_mso_authority_binding(entry, policy_review)
    except ValueError as exc:
        return 422, {
            "ok": False,
            "error": str(exc),
            "execution_allowed": False,
            "can_execute_now": False,
        }

    return 200, {
        "ok": True,
        "entry_id": binding.entry_id,
        "action_id": binding.action_id,
        "policy_review_id": binding.policy_review_id,
        "authority_binding_id": binding.authority_binding_id,
        "binding_status": binding.binding_status,
        "requires_authorized_plan": binding.requires_authorized_plan,
        "requires_police_gate": binding.requires_police_gate,
        "execution_allowed": False,
        "can_execute_now": False,
        "used_execution": False,
        "created_at": binding.created_at.isoformat(),
        "note": (
            "Authority binding draft recorded. "
            "AuthorizedPlan, PoliceGate, and execution still required."
        ),
    }
```

- [ ] **Step 2.2: Add the handler method**

Insert after `_handle_mso_prepared_actions_policy_review_post` (around line 4905, before `_handle_mso_seat_provider_get`):

```python
def _handle_mso_prepared_actions_authority_binding_post(self) -> None:
    """POST /mso/prepared-actions/authority-binding — create MSOAuthorityBindingDraft.

    Second authority chain artifact after MSOPolicyDecisionDraft.
    Requires an approved (not denied) policy review.
    Does NOT call token_issuer, create OperationBinding/AuthorizedPlan,
    call PoliceGate, or invoke runner. execution_allowed remains False.
    """
    auth_error = self._check_auth()
    if auth_error:
        status, error = auth_error
        self._send_json_response(status, error)
        return

    body = self._read_body()
    status, response = _process_mso_authority_binding_request(body)
    self._send_json_response(status, response)
```

- [ ] **Step 2.3: Add the route in do_POST()**

After the policy-review route (around line 1621):

```python
# S-MSO-AUTHORITY-01: create MSOAuthorityBindingDraft for an approved policy review
if path == "/mso/prepared-actions/authority-binding":
    self._handle_mso_prepared_actions_authority_binding_post()
    return
```

- [ ] **Step 2.4: Update the GET pending merge chain**

In `_handle_mso_prepared_actions_pending_get()`, update the merge chain from:
```python
from .mso.human_confirmation import merge_confirmation_into_dict
from .mso.policy_review import merge_policy_review_into_dict
from .mso.prepared_action_queue import list_pending_confirmable_action_dicts
items = [
    merge_policy_review_into_dict(merge_confirmation_into_dict(i))
    for i in list_pending_confirmable_action_dicts()
]
```
to:
```python
from .mso.human_confirmation import merge_confirmation_into_dict
from .mso.policy_review import merge_policy_review_into_dict
from .mso.authority_binding import merge_authority_binding_into_dict
from .mso.prepared_action_queue import list_pending_confirmable_action_dicts
items = [
    merge_authority_binding_into_dict(
        merge_policy_review_into_dict(merge_confirmation_into_dict(i))
    )
    for i in list_pending_confirmable_action_dicts()
]
```

- [ ] **Step 2.5: Run the full test file**

```
python -m pytest tests/test_mso_authority_binding.py -v --tb=short
```
Expected: all 34 tests pass

- [ ] **Step 2.6: Run regression tests**

```
python -m pytest tests/test_mso_policy_review.py -v --tb=short -q
```
Expected: 43 passed

- [ ] **Step 2.7: Commit**

```bash
git add assistant_os/webhook_server.py
git commit -m "feat(mso): add POST /mso/prepared-actions/authority-binding endpoint (Task 2) — 05.4"
```

---

## Task 3: Create Next.js proxy + types + API function

**Files:**
- Create: `ui/app/api/mso/prepared-actions/authority-binding/route.ts`
- Modify: `ui/lib/types.ts`
- Modify: `ui/lib/sovereign/api.ts`

- [ ] **Step 3.1: Create the Next.js proxy route**

Create `ui/app/api/mso/prepared-actions/authority-binding/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server'
import { getWebhookBaseUrl, getWebhookHeaders } from '@/lib/server/webhook-auth'

export const dynamic = 'force-dynamic'

const UNAVAILABLE_RESPONSE = {
  ok: false,
  error: 'Authority binding endpoint unavailable',
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

  const url = `${getWebhookBaseUrl()}/mso/prepared-actions/authority-binding`

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
      { ...UNAVAILABLE_RESPONSE, error: `Authority binding backend unavailable: ${message}` },
      { status: 502 },
    )
  }

  let payload: unknown
  try {
    payload = await upstreamRes.json()
  } catch {
    return NextResponse.json(
      {
        ...UNAVAILABLE_RESPONSE,
        error: `Authority binding backend returned non-JSON (${upstreamRes.status})`,
      },
      { status: 502 },
    )
  }

  return NextResponse.json(payload, { status: upstreamRes.status })
}
```

- [ ] **Step 3.2: Update ui/lib/types.ts**

Add optional authority binding fields to `PreparedActionQueueEntry` (after the policy review fields):

```typescript
  // Authority binding overlay fields (merged at read time from MSOAuthorityBindingDraft)
  authority_binding_id?: string
  authority_binding_status?: string
  authority_binding_created_at?: string
  requires_authorized_plan?: boolean
  requires_police_gate?: boolean
```

Add `MSOAuthorityBindingResult` interface (after `MSOPolicyReviewResult`):

```typescript
// ── MSO authority binding (S-MSO-AUTHORITY-01) ───────────────────────────

export interface MSOAuthorityBindingResult {
  ok: boolean
  entry_id?: string
  action_id?: string
  policy_review_id?: string
  authority_binding_id?: string
  binding_status?: string
  requires_authorized_plan?: boolean
  requires_police_gate?: boolean
  execution_allowed: false
  can_execute_now: false
  used_execution?: false
  created_at?: string
  note?: string
  error?: string
  policy_outcome?: string
}
```

- [ ] **Step 3.3: Add requestMSOAuthorityBinding() to ui/lib/sovereign/api.ts**

Add the import:
```typescript
import type { ConfirmPreparedActionResult, MSOPolicyReviewResult, MSOAuthorityBindingResult } from '../types'
```

Add the function (after `requestMSOPolicyReview`):

```typescript
/**
 * Request MSO authority binding draft for an approved policy review.
 * Produces MSOAuthorityBindingDraft — second authority chain artifact after MSOPolicyDecisionDraft.
 * Requires policy_outcome to be "approved" or "approved_confirm_only".
 * Does not call token_issuer, create AuthorizedPlan, call PoliceGate, or execute.
 * execution_allowed and can_execute_now remain false.
 */
export async function requestMSOAuthorityBinding(
  entryId: string,
  actionId: string,
): Promise<MSOAuthorityBindingResult> {
  try {
    const res = await fetch('/api/mso/prepared-actions/authority-binding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entry_id: entryId, action_id: actionId }),
    })
    const data = await res.json()
    if (!res.ok) {
      return {
        ok: false,
        execution_allowed: false,
        can_execute_now: false,
        error: data.error ?? `Error ${res.status}`,
        policy_outcome: data.policy_outcome,
      }
    }
    return {
      ok: true,
      entry_id: data.entry_id,
      action_id: data.action_id,
      policy_review_id: data.policy_review_id,
      authority_binding_id: data.authority_binding_id,
      binding_status: data.binding_status,
      requires_authorized_plan: data.requires_authorized_plan,
      requires_police_gate: data.requires_police_gate,
      execution_allowed: false,
      can_execute_now: false,
      used_execution: false,
      created_at: data.created_at,
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

- [ ] **Step 3.4: Commit**

```bash
git add ui/app/api/mso/prepared-actions/authority-binding/route.ts ui/lib/types.ts ui/lib/sovereign/api.ts
git commit -m "feat(mso): add authority-binding proxy route, types, and API function (Task 3) — 05.4"
```

---

## Task 4: Update PreparedActionConfirmSurface with authority binding badge

**Files:**
- Modify: `ui/components/sovereign/PreparedActionConfirmSurface.tsx`

After a successful policy review with `policy_outcome` in `"approved"` or `"approved_confirm_only"`, auto-trigger `requestMSOAuthorityBinding()`. Show a badge with `binding_status` if the binding was created. If policy is denied, do not trigger.

- [ ] **Step 4.1: Update PreparedActionConfirmSurface.tsx**

Replace the entire file contents:

```tsx
'use client'

import { useState } from 'react'
import type { PreparedActionQueueEntry, MSOPolicyReviewResult, MSOAuthorityBindingResult } from '@/lib/types'
import { confirmPreparedAction, requestMSOPolicyReview, requestMSOAuthorityBinding } from '@/lib/sovereign/api'
import { getPreparedActionsPending } from '@/lib/api'
import { usePreparedActionsStore } from '@/stores/prepared-actions-store'

const POLICY_OUTCOME_LABELS: Record<string, string> = {
  approved: 'Policy: Approved',
  approved_confirm_only: 'Policy: Approved (confirm-only)',
  denied: 'Policy: Denied',
}

const POLICY_OUTCOME_COLORS: Record<string, string> = {
  approved: 'text-ok',
  approved_confirm_only: 'text-ok',
  denied: 'text-warn',
}

const APPROVED_OUTCOMES = new Set(['approved', 'approved_confirm_only'])

export function PreparedActionConfirmSurface({ item }: { item: PreparedActionQueueEntry }) {
  const [isConfirming, setIsConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [localStatus, setLocalStatus] = useState<string | null>(null)
  const [policyReview, setPolicyReview] = useState<MSOPolicyReviewResult | null>(null)
  const [policyError, setPolicyError] = useState<string | null>(null)
  const [authorityBinding, setAuthorityBinding] = useState<MSOAuthorityBindingResult | null>(null)
  const [bindingError, setBindingError] = useState<string | null>(null)
  const setPreparedActions = usePreparedActionsStore((s) => s.setPreparedActions)

  const effectiveStatus = localStatus ?? item.human_confirmation_status
  const effectivePolicyOutcome = policyReview?.policy_outcome ?? item.policy_outcome
  const effectiveBindingStatus = authorityBinding?.binding_status ?? item.authority_binding_status

  async function handleConfirm(confirmed: boolean) {
    if (isConfirming) return
    setIsConfirming(true)
    setConfirmError(null)
    setPolicyError(null)
    setBindingError(null)
    try {
      const result = await confirmPreparedAction(
        item.queue_entry_id,
        item.prepared_action_id ?? item.queue_entry_id,
        confirmed,
      )
      if (!result.ok) {
        setConfirmError(result.error ?? 'Confirm request failed')
        return
      }
      setLocalStatus(result.human_confirmation_status ?? (confirmed ? 'human_confirmed' : 'human_rejected'))

      if (confirmed) {
        const review = await requestMSOPolicyReview(
          item.queue_entry_id,
          item.prepared_action_id ?? item.queue_entry_id,
        )
        setPolicyReview(review)
        if (!review.ok) {
          setPolicyError(review.error ?? 'Policy review failed')
        } else if (review.policy_outcome && APPROVED_OUTCOMES.has(review.policy_outcome)) {
          const binding = await requestMSOAuthorityBinding(
            item.queue_entry_id,
            item.prepared_action_id ?? item.queue_entry_id,
          )
          setAuthorityBinding(binding)
          if (!binding.ok) {
            setBindingError(binding.error ?? 'Authority binding failed')
          }
        }
      }

      const refreshed = await getPreparedActionsPending()
      setPreparedActions(refreshed)
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : 'Network error')
    } finally {
      setIsConfirming(false)
    }
  }

  if (effectiveStatus === 'human_confirmed' || effectiveStatus === 'human_rejected') {
    const label = effectiveStatus === 'human_confirmed' ? 'Confirmed' : 'Rejected'
    const color = effectiveStatus === 'human_confirmed' ? 'text-ok' : 'text-warn'
    return (
      <div className="mt-3 pt-2 border-t border-os-border/60">
        <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
          Human Confirmation Signal
        </p>
        <p className={`text-[10px] font-mono ${color}`}>Signal recorded: {label}</p>
        {effectivePolicyOutcome && (
          <p className={`text-[10px] font-mono mt-1 ${POLICY_OUTCOME_COLORS[effectivePolicyOutcome] ?? 'text-tx-muted'}`}>
            {POLICY_OUTCOME_LABELS[effectivePolicyOutcome] ?? effectivePolicyOutcome}
          </p>
        )}
        {policyError && (
          <p className="text-[10px] font-mono text-warn mt-1">{policyError}</p>
        )}
        {effectiveBindingStatus && (
          <p className="text-[10px] font-mono text-ok mt-1">
            Authority binding: {effectiveBindingStatus}
          </p>
        )}
        {bindingError && (
          <p className="text-[10px] font-mono text-warn mt-1">{bindingError}</p>
        )}
        <p className="text-[10px] font-mono text-tx-muted mt-1 leading-relaxed">
          Signal recorded. Execution remains closed pending full authority chain.
        </p>
      </div>
    )
  }

  return (
    <div className="mt-3 pt-2 border-t border-os-border/60">
      <p className="text-[9px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-1">
        Human Confirmation Signal
      </p>
      <p className="text-[10px] font-mono text-tx-muted mb-2 leading-relaxed">
        Record a human signal only. Does not execute, approve, or authorize. execution_allowed remains false.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={isConfirming}
          onClick={() => handleConfirm(true)}
          className="px-3 py-1 text-[10px] font-mono rounded border border-os-border text-tx-secondary hover:text-tx-primary hover:border-tx-muted disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isConfirming ? 'Recording…' : 'Confirm Review'}
        </button>
        <button
          type="button"
          disabled={isConfirming}
          onClick={() => handleConfirm(false)}
          className="px-3 py-1 text-[10px] font-mono rounded border border-os-border text-warn hover:border-warn disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isConfirming ? 'Recording…' : 'Reject'}
        </button>
      </div>
      {confirmError && (
        <p className="text-[10px] font-mono text-warn mt-2">{confirmError}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 4.2: Commit**

```bash
git add ui/components/sovereign/PreparedActionConfirmSurface.tsx
git commit -m "feat(mso): auto-trigger authority binding after approved policy review + badge (Task 4) — 05.4"
```

---

## Task 5: Full verification + PR

- [ ] **Step 5.1: Run the full authority binding test suite**

```
python -m pytest tests/test_mso_authority_binding.py -v --tb=short
```
Expected: 34 passed

- [ ] **Step 5.2: Run regression tests**

```
python -m pytest tests/test_mso_policy_review.py tests/ -k "panel or contract or confirm_surface or policy_review or authority_binding" --tb=short -q
```
Expected: all pass, no regressions

- [ ] **Step 5.3: Push and create PR**

```bash
GIT_SSL_NO_VERIFY=true git push -u origin claude/elegant-williamson-391927
gh pr create --repo JorgeCast31/Assistant_OS_Labs \
  --title "feat(mso): SPRINT-ALPHA-05.4 — MSOAuthorityBindingDraft Bridge" \
  --body "..."
```

---

## Self-Review

### Spec coverage check

| Requirement | Task |
|-------------|------|
| No policy review → fail closed | Task 2, endpoint test `test_no_policy_review_returns_422` |
| Denied → fail closed | Task 2, endpoint test `test_denied_policy_review_returns_422` |
| Approved → create binding | Task 1+2, `test_approved_creates_binding` |
| approved_confirm_only → create binding | Task 1+2, `test_approved_confirm_only_creates_binding` |
| Idempotent by queue_entry_id | Task 1, `test_idempotent_same_id_on_duplicate_call` |
| Duplicate POST → same artifact ID | Task 2, `test_duplicate_post_returns_same_binding_id` |
| execution_allowed=False invariant | Task 1, `test_execution_allowed_invariant_raises_on_true` |
| can_execute_now=False invariant | Task 1, `test_can_execute_now_invariant_raises_on_true` |
| used_execution=False invariant | Task 1, `test_used_execution_invariant_raises_on_true` |
| No AuthorizedPlan | Task 1+2, `test_no_authorized_plan_field_in_response` |
| No PoliceGate | Task 1+2, `test_no_runner_field_in_response` |
| No runner | Task 1+2, `test_no_runner_field_in_response` |
| Merged into GET pending | Task 2 merge chain + `test_merge_overlays_authority_binding_fields` |
| UI badge after confirm | Task 4 |
| Passive panels remain passive | Existing contract tests (not modified) |
| requires_authorized_plan=True in response | Task 2, `test_success_requires_authorized_plan_true` |
| requires_police_gate=True in response | Task 2, `test_success_requires_police_gate_true` |

### Placeholder scan
No TBD, TODO, or placeholder strings.

### Type consistency
- `MSOAuthorityBindingDraft.authority_binding_id` ↔ `MSOAuthorityBindingResult.authority_binding_id` ✓
- `binding_status` used consistently as string field ✓
- `merge_authority_binding_into_dict` uses `authority_binding_status` key in result dict ✓
- `PreparedActionQueueEntry.authority_binding_status` matches key from merge function ✓
