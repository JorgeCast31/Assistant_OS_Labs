"""S-MSO-DIRECT-GOVERNED-CONFIRMATION-BRIDGE-01: Governed Confirmation Bridge tests.

Verifies that the governed confirmation bridge module and the mso_direct routing layer:
  1.  Bridge helper returns used_execution=False (always).
  2.  Bridge helper returns can_execute_now=False (always).
  3.  Bridge includes normalized intent metadata.
  4.  Bridge includes required authority path with correct chain.
  5.  Bridge includes next_safe_action.
  6.  mso_direct "turn this into a confirmable action" routes to bridge.
  7.  Spanish prompt "prepara esto para ejecución" routes to bridge.
  8.  mso_direct bridge response includes authority_trace_summary.
  9.  mso_direct bridge response does not call Runner (used_execution=False).
 10.  mso_direct bridge response does not call Police (execution_status not_executed).
 11.  If prepared action creation is deferred, bridge reports created=False honestly.
 12.  Existing MSO status / seat / intent / trace tests still pass (coverage breadth).

None of these tests invoke a live LLM, call network services, or start a server.
The bridge is a pure read model — no side effects beyond the prepared-action queue,
which is cleared by the autouse fixture to guarantee test isolation.
"""
from __future__ import annotations

import pytest

from assistant_os.mso.governed_confirmation_bridge import (
    BRIDGE_ENTITY,
    BRIDGE_TYPE,
    BRIDGE_VERSION,
    REQUIRED_AUTHORITY_CHAIN,
    build_governed_confirmation_bridge,
    is_governed_preparation_prompt,
)
from assistant_os.surface_behavior import get_surface_behavior_response


# ---------------------------------------------------------------------------
# Shared stubs (mirrors other mso test suites)
# ---------------------------------------------------------------------------


class _AuditStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_audit_dict(self) -> dict:
        return dict(self._payload)


# ---------------------------------------------------------------------------
# Autouse fixture — reset MSO state around every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_mso_state():
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass
    try:
        from assistant_os.context_store import clear_store
        clear_store()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass
    yield
    try:
        from assistant_os.mso.task_registry import reset_task_registry
        from assistant_os.mso.capability_registry import reset_dynamic_capabilities
        reset_dynamic_capabilities()
        reset_task_registry()
    except Exception:
        pass
    try:
        from assistant_os.mso.prepared_action_queue import clear_confirmable_action_queue_for_tests
        clear_confirmable_action_queue_for_tests()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routing helper
# ---------------------------------------------------------------------------


def _route_bridge(text: str, mso_context: dict | None = None) -> dict | None:
    """Route a request through mso_direct and return the response."""
    return get_surface_behavior_response(
        surface="mso_direct",
        text=text,
        context_id="ctx-bridge-test",
        identity=_AuditStub({"principal": "anon"}),
        guard_result=_AuditStub({"decision": "allow"}),
        mso_context=mso_context,
    )


def _build_bridge(
    text: str = "turn this into a confirmable action",
    intent_metadata: dict | None = None,
    prepared_action_data: dict | None = None,
) -> dict:
    """Build the bridge response directly via the module helper."""
    return build_governed_confirmation_bridge(
        text=text,
        intent_metadata=intent_metadata,
        mso_context=None,
        prepared_action_data=prepared_action_data,
    )


# ---------------------------------------------------------------------------
# Detection function tests
# ---------------------------------------------------------------------------


class TestIsGovernedPreparationPrompt:
    """is_governed_preparation_prompt(text) — pure detection, no side effects."""

    # English bridge phrases
    def test_detects_turn_this_into_confirmable_action(self):
        assert is_governed_preparation_prompt("turn this into a confirmable action") is True

    def test_detects_prepare_this_action(self):
        assert is_governed_preparation_prompt("prepare this action") is True

    def test_detects_prepare_governed_action(self):
        assert is_governed_preparation_prompt("prepare governed action") is True

    def test_detects_plan_this_for_execution(self):
        assert is_governed_preparation_prompt("plan this for execution") is True

    def test_detects_validate_this_before_execution(self):
        assert is_governed_preparation_prompt("validate this before execution") is True

    def test_detects_validate_before_executing(self):
        assert is_governed_preparation_prompt("validate before executing") is True

    def test_detects_guided_execution(self):
        assert is_governed_preparation_prompt("guided execution") is True

    def test_detects_confirmable_action(self):
        assert is_governed_preparation_prompt("confirmable action") is True

    def test_detects_mso_prepare(self):
        assert is_governed_preparation_prompt("mso, prepare") is True

    def test_detects_what_is_next_safe_step(self):
        assert is_governed_preparation_prompt("what is the next safe step") is True

    # Spanish bridge phrases
    def test_detects_prepara_esto_para_ejecucion_accented(self):
        """Accented 'ejecución' must be stripped and matched."""
        assert is_governed_preparation_prompt("prepara esto para ejecución") is True

    def test_detects_prepara_esto_para_ejecucion_unaccented(self):
        assert is_governed_preparation_prompt("prepara esto para ejecucion") is True

    def test_detects_accion_confirmable(self):
        assert is_governed_preparation_prompt("acción confirmable") is True

    def test_detects_validar_antes_de_ejecutar(self):
        assert is_governed_preparation_prompt("validar antes de ejecutar") is True

    def test_detects_proximo_paso_seguro(self):
        assert is_governed_preparation_prompt("próximo paso seguro") is True

    def test_detects_orquestar_con_gobernanza(self):
        assert is_governed_preparation_prompt("orquestar con gobernanza") is True

    # Non-bridge phrases — must NOT trigger
    def test_does_not_detect_ordinary_hello(self):
        assert is_governed_preparation_prompt("hola") is False

    def test_does_not_detect_mso_status(self):
        assert is_governed_preparation_prompt("mso status") is False

    def test_does_not_detect_prepare_a_plan(self):
        """'prepare a plan' (plan_request) must NOT trigger the bridge."""
        assert is_governed_preparation_prompt("prepare a plan") is False

    def test_does_not_detect_empty_string(self):
        assert is_governed_preparation_prompt("") is False

    def test_does_not_detect_none_like_non_string(self):
        assert is_governed_preparation_prompt("   ") is False

    def test_does_not_detect_generic_execution_word(self):
        """The word 'execution' alone is not a bridge phrase."""
        assert is_governed_preparation_prompt("execution") is False


# ---------------------------------------------------------------------------
# Test 1 & 2: Bridge helper invariants — used_execution / can_execute_now
# ---------------------------------------------------------------------------


class TestBridgeHelperExecutionInvariants:
    """build_governed_confirmation_bridge always returns safe execution flags."""

    def test_used_execution_is_false(self):
        """TEST 1: Bridge helper returns used_execution=False."""
        result = _build_bridge()
        assert result["used_execution"] is False

    def test_can_execute_now_is_false(self):
        """TEST 2: Bridge helper returns can_execute_now=False."""
        result = _build_bridge()
        assert result["can_execute_now"] is False

    def test_execution_allowed_is_false(self):
        result = _build_bridge()
        assert result["execution_allowed"] is False

    def test_invariants_hold_with_prepared_action_data(self):
        """Invariants must hold even when prepared_action_data is provided."""
        fake_data = {
            "queued_prepared_action": {
                "queue_entry_id": "qe-fake-id",
                "prepared_action_id": "cpa-fake-id",
            }
        }
        result = _build_bridge(prepared_action_data=fake_data)
        assert result["used_execution"] is False
        assert result["can_execute_now"] is False
        assert result["execution_allowed"] is False

    def test_invariants_hold_with_empty_text(self):
        """Fail-soft: invariants must hold even for empty text input."""
        result = _build_bridge(text="")
        assert result["used_execution"] is False
        assert result["can_execute_now"] is False
        assert result["execution_allowed"] is False

    def test_bridge_never_raises(self):
        """Bridge must not raise on any input — fail-soft outer wrapper."""
        import json
        # Deliberately bad intent_metadata — bridge must absorb and return safely
        result = build_governed_confirmation_bridge(
            text="turn this into a confirmable action",
            intent_metadata={"intent_mode": "INVALID_FABRICATED"},
            mso_context=None,
            prepared_action_data=None,
        )
        assert isinstance(result, dict)
        assert result["used_execution"] is False


# ---------------------------------------------------------------------------
# Test 3: Bridge includes normalized intent metadata
# ---------------------------------------------------------------------------


class TestBridgeIntentMetadata:
    """TEST 3: Bridge helper includes normalized intent_metadata."""

    def test_intent_metadata_present(self):
        result = _build_bridge()
        assert "intent_metadata" in result

    def test_intent_metadata_is_dict(self):
        result = _build_bridge()
        assert isinstance(result["intent_metadata"], dict)

    def test_intent_metadata_intent_mode_is_planning(self):
        """Bridge always targets planning intent_mode."""
        from assistant_os.mso.intent_contract import normalize_mso_intent_metadata, INTENT_MODE_PLANNING
        result = _build_bridge(
            intent_metadata=normalize_mso_intent_metadata(
                {"intent_mode": INTENT_MODE_PLANNING, "execution_intent": False}
            )
        )
        assert result["intent_metadata"]["intent_mode"] == "planning"

    def test_intent_metadata_execution_intent_false(self):
        """Bridge intent always has execution_intent=False."""
        result = _build_bridge()
        assert result["intent_metadata"].get("execution_intent") is False


# ---------------------------------------------------------------------------
# Test 4: Bridge includes required authority path
# ---------------------------------------------------------------------------


class TestBridgeAuthorityPath:
    """TEST 4: Bridge includes authority_path with the correct required chain."""

    def test_authority_path_present(self):
        result = _build_bridge()
        assert "authority_path" in result

    def test_authority_path_has_required_chain(self):
        result = _build_bridge()
        chain = result["authority_path"]["required_chain"]
        assert isinstance(chain, list)
        assert len(chain) == len(REQUIRED_AUTHORITY_CHAIN)

    def test_authority_path_chain_matches_canonical(self):
        result = _build_bridge()
        chain = result["authority_path"]["required_chain"]
        assert chain == list(REQUIRED_AUTHORITY_CHAIN)

    def test_authority_path_current_stage_is_proposal(self):
        result = _build_bridge()
        assert result["authority_path"]["current_stage"] == "proposal"

    def test_authority_path_next_stage_is_human_confirmation(self):
        result = _build_bridge()
        assert result["authority_path"]["next_required_stage"] == "human_confirmation"

    def test_authority_path_chain_note_present(self):
        result = _build_bridge()
        assert result["authority_path"].get("chain_note")

    def test_canonical_chain_order(self):
        """The required authority chain must follow the canonical contract order."""
        expected = [
            "MSO Kernel",
            "Policy",
            "Governance",
            "CapabilityToken",
            "Police",
            "AuthorityArtifact",
            "Runner",
        ]
        assert list(REQUIRED_AUTHORITY_CHAIN) == expected


# ---------------------------------------------------------------------------
# Test 5: Bridge includes next_safe_action
# ---------------------------------------------------------------------------


class TestBridgeNextSafeAction:
    """TEST 5: Bridge includes next_safe_action string."""

    def test_next_safe_action_present(self):
        result = _build_bridge()
        assert "next_safe_action" in result

    def test_next_safe_action_is_string(self):
        result = _build_bridge()
        assert isinstance(result["next_safe_action"], str)

    def test_next_safe_action_is_non_empty(self):
        result = _build_bridge()
        assert result["next_safe_action"].strip()

    def test_next_safe_action_mentions_governed_flow(self):
        """next_safe_action must guide toward the governed flow, not free execution."""
        result = _build_bridge()
        nsa = result["next_safe_action"].lower()
        assert any(kw in nsa for kw in ("govern", "confirm", "review", "authority", "queue"))

    def test_next_safe_action_mentions_queue_entry_when_created(self):
        """When a prepared action was created, next_safe_action must reference its queue_entry_id."""
        fake_data = {
            "queued_prepared_action": {
                "queue_entry_id": "qe-specific-id-xyz",
                "prepared_action_id": "cpa-specific-id",
            }
        }
        result = _build_bridge(prepared_action_data=fake_data)
        assert "qe-specific-id-xyz" in result["next_safe_action"]


# ---------------------------------------------------------------------------
# Test 6: mso_direct routes "turn this into a confirmable action" to bridge
# ---------------------------------------------------------------------------


class TestMsoDirectBridgeRoutingEnglish:
    """TEST 6: English bridge phrase routes to the governed confirmation bridge."""

    def test_routes_to_bridge(self):
        resp = _route_bridge("turn this into a confirmable action")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_response_has_governed_confirmation_bridge_key(self):
        resp = _route_bridge("turn this into a confirmable action")
        assert "governed_confirmation_bridge" in resp

    def test_bridge_block_has_correct_bridge_type(self):
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["bridge_type"] == BRIDGE_TYPE

    def test_bridge_block_has_correct_entity(self):
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["entity"] == BRIDGE_ENTITY

    def test_bridge_block_has_correct_version(self):
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["bridge_version"] == BRIDGE_VERSION

    def test_validate_before_executing_also_routes(self):
        resp = _route_bridge("validate before executing")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_confirmable_action_phrase_routes(self):
        resp = _route_bridge("confirmable action")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_what_is_next_safe_step_routes(self):
        resp = _route_bridge("what is the next safe step")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"


# ---------------------------------------------------------------------------
# Test 7: Spanish prompt "prepara esto para ejecución" routes to bridge
# ---------------------------------------------------------------------------


class TestMsoDirectBridgeRoutingSpanish:
    """TEST 7: Spanish bridge phrases route to the governed confirmation bridge."""

    def test_prepara_esto_para_ejecucion_accented(self):
        """TEST 7a: Accented 'ejecución' must route to bridge."""
        resp = _route_bridge("prepara esto para ejecución")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_prepara_esto_para_ejecucion_unaccented(self):
        """TEST 7b: Unaccented variant must also route to bridge."""
        resp = _route_bridge("prepara esto para ejecucion")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_accion_confirmable_routes(self):
        resp = _route_bridge("acción confirmable")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_validar_antes_de_ejecutar_routes(self):
        resp = _route_bridge("validar antes de ejecutar")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_proximo_paso_seguro_routes(self):
        resp = _route_bridge("próximo paso seguro")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_orquestar_con_gobernanza_routes(self):
        resp = _route_bridge("orquestar con gobernanza")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"

    def test_orquestar_con_confirmacion_routes(self):
        resp = _route_bridge("orquestar con confirmación")
        assert resp is not None
        assert resp.get("intent") == "mso_governed_confirmation_bridge"


# ---------------------------------------------------------------------------
# Test 8: mso_direct bridge response includes authority_trace_summary
# ---------------------------------------------------------------------------


class TestBridgeResponseAuthorityTraceSummary:
    """TEST 8: mso_direct bridge response includes authority_trace_summary."""

    def test_authority_trace_summary_present(self):
        resp = _route_bridge("turn this into a confirmable action")
        assert "authority_trace_summary" in resp

    def test_authority_trace_summary_is_dict(self):
        resp = _route_bridge("turn this into a confirmable action")
        assert isinstance(resp["authority_trace_summary"], dict)

    def test_authority_trace_summary_has_trace_key(self):
        """authority_trace_summary must have a 'trace' or 'steps' or 'chain' key
        from build_authority_trace_snapshot."""
        resp = _route_bridge("turn this into a confirmable action")
        summary = resp["authority_trace_summary"]
        # build_authority_trace_snapshot returns at least one of these keys
        assert any(k in summary for k in ("trace", "steps", "authority_chain", "chain"))


# ---------------------------------------------------------------------------
# Test 9: mso_direct bridge response does NOT call Runner
# ---------------------------------------------------------------------------


class TestBridgeDoesNotCallRunner:
    """TEST 9: Bridge must not invoke the Runner in any form."""

    def test_used_execution_is_false_in_response(self):
        """used_execution=False signals no execution path was triggered."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp["used_execution"] is False

    def test_execution_status_is_not_executed(self):
        """execution_status=not_executed confirms no execution occurred."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp.get("execution_status") == "not_executed"

    def test_response_source_is_bridge(self):
        """response_source must be 'mso_governed_confirmation_bridge', not a runner."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp.get("response_source") == "mso_governed_confirmation_bridge"

    def test_bridge_block_execution_allowed_false(self):
        """The nested bridge block must also have execution_allowed=False."""
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["execution_allowed"] is False

    def test_operation_trace_confirms_no_execution(self):
        """operation_trace must explicitly state execution_allowed=False."""
        resp = _route_bridge("turn this into a confirmable action")
        op_trace = resp.get("operation_trace", {})
        assert op_trace.get("execution_allowed") is False
        assert op_trace.get("used_execution") is False

    def test_operation_trace_confirmation_required(self):
        """operation_trace must state confirmation_required=True."""
        resp = _route_bridge("turn this into a confirmable action")
        op_trace = resp.get("operation_trace", {})
        assert op_trace.get("confirmation_required") is True


# ---------------------------------------------------------------------------
# Test 10: mso_direct bridge response does NOT call Police
# ---------------------------------------------------------------------------


class TestBridgeDoesNotCallPolice:
    """TEST 10: Bridge must not call the Police gate in any form."""

    def test_can_execute_now_is_false(self):
        """can_execute_now=False confirms no Police-authorized execution path was opened."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp["can_execute_now"] is False

    def test_no_police_decision_in_response(self):
        """No police_decision key should be present at the top level of the bridge response."""
        resp = _route_bridge("turn this into a confirmable action")
        # A Police gate call would produce a 'police_decision' key
        assert "police_decision" not in resp

    def test_bridge_block_can_execute_now_false(self):
        """The nested bridge block must also have can_execute_now=False."""
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["can_execute_now"] is False

    def test_operation_trace_can_execute_now_false(self):
        """operation_trace must have can_execute_now=False."""
        resp = _route_bridge("turn this into a confirmable action")
        op_trace = resp.get("operation_trace", {})
        assert op_trace.get("can_execute_now") is False

    def test_authority_path_stage_is_proposal_not_police(self):
        """Authority path current_stage must be 'proposal', not 'police' or later."""
        resp = _route_bridge("turn this into a confirmable action")
        bridge = resp["governed_confirmation_bridge"]
        assert bridge["authority_path"]["current_stage"] == "proposal"

    def test_bridge_domain_is_mso_not_pipeline(self):
        """Bridge response domain must be 'MSO', not an executing pipeline domain."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp.get("domain") == "MSO"


# ---------------------------------------------------------------------------
# Test 11: Bridge reports created=False honestly when no prepared action
# ---------------------------------------------------------------------------


class TestBridgePreparedActionHonesty:
    """TEST 11: Bridge states prepared_action.created=False when creation was not possible."""

    def test_bridge_helper_created_false_when_no_data(self):
        """Direct call with prepared_action_data=None must return created=False."""
        result = _build_bridge(prepared_action_data=None)
        assert result["prepared_action"]["created"] is False

    def test_bridge_helper_created_false_empty_dict(self):
        """Empty prepared_action_data must return created=False."""
        result = _build_bridge(prepared_action_data={})
        assert result["prepared_action"]["created"] is False

    def test_bridge_helper_created_false_missing_queue_entry_id(self):
        """Missing queue_entry_id in prepared_action_data must return created=False."""
        result = _build_bridge(
            prepared_action_data={
                "queued_prepared_action": {
                    # queue_entry_id deliberately missing
                    "prepared_action_id": "cpa-orphan",
                }
            }
        )
        assert result["prepared_action"]["created"] is False

    def test_bridge_helper_created_true_when_queue_entry_id_present(self):
        """When queue_entry_id is present, created must be True."""
        result = _build_bridge(
            prepared_action_data={
                "queued_prepared_action": {
                    "queue_entry_id": "qe-real-id",
                    "prepared_action_id": "cpa-real-id",
                }
            }
        )
        assert result["prepared_action"]["created"] is True

    def test_bridge_helper_id_is_none_when_not_created(self):
        """prepared_action.id must be None when created=False."""
        result = _build_bridge(prepared_action_data=None)
        assert result["prepared_action"]["id"] is None

    def test_bridge_helper_id_is_queue_entry_when_created(self):
        """prepared_action.id must be the queue_entry_id when created=True."""
        result = _build_bridge(
            prepared_action_data={
                "queued_prepared_action": {
                    "queue_entry_id": "qe-confirmed-id",
                }
            }
        )
        assert result["prepared_action"]["id"] == "qe-confirmed-id"

    def test_bridge_helper_reason_is_honest_when_not_created(self):
        """prepared_action.reason must be set (not empty) when created=False."""
        result = _build_bridge(prepared_action_data=None)
        reason = result["prepared_action"]["reason"]
        assert isinstance(reason, str)
        assert reason.strip()

    def test_bridge_status_reflects_prepared_action_state(self):
        """status must be 'proposal_ready' when no action was created."""
        result = _build_bridge(
            text="turn this into a confirmable action",
            prepared_action_data=None,
        )
        assert result["status"] == "proposal_ready"

    def test_bridge_status_is_prepared_action_created_when_id_present(self):
        """status must be 'prepared_action_created' when a queue entry ID exists."""
        result = _build_bridge(
            prepared_action_data={
                "queued_prepared_action": {
                    "queue_entry_id": "qe-status-check",
                }
            }
        )
        assert result["status"] == "prepared_action_created"


# ---------------------------------------------------------------------------
# Test 12 — Coverage breadth: bridge phrases do not break existing routing
# ---------------------------------------------------------------------------


class TestExistingRoutingUnaffected:
    """TEST 12: Bridge intercept must not disrupt existing mso_direct routing paths.

    These tests verify that non-bridge phrases still route correctly,
    ensuring SPRINT-BRIDGE-01 is additive and does not regress prior behavior.
    """

    def test_status_phrase_still_routes_to_status(self):
        """'mso status' must NOT trigger the bridge — must remain a status query."""
        resp = _route_bridge("mso status")
        assert resp is not None
        assert resp.get("intent") != "mso_governed_confirmation_bridge"

    def test_estado_del_mso_still_routes_to_status(self):
        """'estado del mso' must NOT trigger the bridge."""
        resp = _route_bridge("estado del mso")
        assert resp is not None
        assert resp.get("intent") != "mso_governed_confirmation_bridge"

    def test_hello_still_routes_to_conversational(self):
        """'hola' must NOT trigger the bridge."""
        resp = _route_bridge("hola")
        assert resp is not None
        assert resp.get("intent") != "mso_governed_confirmation_bridge"

    def test_plan_request_phrase_does_not_trigger_bridge(self):
        """'prepare a plan' (plan_request) must NOT trigger the bridge — it has its own path."""
        assert is_governed_preparation_prompt("prepare a plan") is False

    def test_solo_plan_does_not_trigger_bridge(self):
        """'solo plan' is a plan_request phrase — must NOT trigger the bridge."""
        assert is_governed_preparation_prompt("solo plan") is False


# ---------------------------------------------------------------------------
# Bridge module metadata / structure tests
# ---------------------------------------------------------------------------


class TestBridgeModuleContract:
    """The bridge module exports the correct metadata and structure."""

    def test_bridge_version_is_string(self):
        assert isinstance(BRIDGE_VERSION, str)

    def test_bridge_type_is_correct(self):
        assert BRIDGE_TYPE == "mso_direct_to_governed_confirmation"

    def test_bridge_entity_is_mso(self):
        assert BRIDGE_ENTITY == "MSO"

    def test_required_authority_chain_is_tuple(self):
        assert isinstance(REQUIRED_AUTHORITY_CHAIN, tuple)

    def test_required_authority_chain_length(self):
        """Chain must contain exactly 7 steps."""
        assert len(REQUIRED_AUTHORITY_CHAIN) == 7

    def test_required_authority_chain_contains_runner(self):
        assert "Runner" in REQUIRED_AUTHORITY_CHAIN

    def test_required_authority_chain_contains_police(self):
        assert "Police" in REQUIRED_AUTHORITY_CHAIN

    def test_required_authority_chain_contains_capability_token(self):
        assert "CapabilityToken" in REQUIRED_AUTHORITY_CHAIN

    def test_bridge_response_has_all_required_top_level_keys(self):
        """The bridge response must include every key required by the sprint spec."""
        required_keys = {
            "bridge_version",
            "entity",
            "bridge_type",
            "status",
            "used_execution",
            "can_execute_now",
            "execution_allowed",
            "intent_metadata",
            "proposal",
            "authority_path",
            "prepared_action",
            "next_safe_action",
        }
        result = _build_bridge()
        assert required_keys.issubset(result.keys())

    def test_proposal_block_requires_confirmation(self):
        """proposal.requires_confirmation must always be True."""
        result = _build_bridge()
        assert result["proposal"]["requires_confirmation"] is True

    def test_proposal_block_has_risk_note(self):
        """proposal.risk_note must be present and non-empty."""
        result = _build_bridge()
        assert result["proposal"].get("risk_note", "").strip()

    def test_proposal_summary_preserved_from_text(self):
        """proposal.summary must reflect the input text."""
        text = "turn this into a confirmable action"
        result = _build_bridge(text=text)
        assert text[:50] in result["proposal"]["summary"]

    def test_mso_direct_response_includes_operation_trace(self):
        """operation_trace must be present in the mso_direct bridge response."""
        resp = _route_bridge("turn this into a confirmable action")
        assert "operation_trace" in resp

    def test_mso_direct_operation_trace_bridge_activated(self):
        """operation_trace.bridge_activated must be True."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp["operation_trace"]["bridge_activated"] is True

    def test_mso_direct_operation_trace_source_surface(self):
        """operation_trace.source_surface must be 'mso_direct'."""
        resp = _route_bridge("turn this into a confirmable action")
        assert resp["operation_trace"]["source_surface"] == "mso_direct"
