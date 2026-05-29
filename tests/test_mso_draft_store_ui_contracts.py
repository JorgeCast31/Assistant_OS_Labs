"""
Static contract tests for the Draft Store UI layer (Sprint #228).

These tests verify structural and semantic boundaries without requiring
a running UI or browser:

1. PlanStateBadge source existence and boundary compliance.
2. TypeScript type contracts in lib/types.ts.
3. API helper contracts in lib/api.ts.
4. No /api/agent/execute import in plan-related routes.
5. No LifecycleBadge reuse in PlanStateBadge.
6. No execution fields in PlanDraftRecord interface.
7. No ExecutionState type usage in PlanStateBadge.
8. source='draft_store' present in all plan API functions.
9. Next.js proxy routes exist and have correct structure.
"""
import pathlib
import re
import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
UI = REPO_ROOT / "ui"


# ---------------------------------------------------------------------------
# PlanStateBadge existence and structure
# ---------------------------------------------------------------------------

class TestPlanStateBadgeExists:
    BADGE_PATH = UI / "components" / "sovereign" / "PlanStateBadge.tsx"

    def test_badge_file_exists(self):
        assert self.BADGE_PATH.exists(), "PlanStateBadge.tsx must exist"

    def test_badge_exported_from_index(self):
        index = (UI / "components" / "sovereign" / "index.ts").read_text()
        assert "PlanStateBadge" in index

    def test_badge_does_not_import_lifecycle_badge(self):
        src = self.BADGE_PATH.read_text()
        # Check import statements only — mentions in comments/docs are OK
        import_lines = [l for l in src.splitlines()
                        if l.strip().startswith("import ") or
                        ("from " in l and "import" in l)]
        for line in import_lines:
            assert "LifecycleBadge" not in line, \
                f"PlanStateBadge must not import LifecycleBadge: {line}"

    def test_badge_does_not_use_execution_state_type(self):
        src = self.BADGE_PATH.read_text()
        # Check import statements only — mentions in docstrings/comments are OK
        import_lines = [l for l in src.splitlines()
                        if l.strip().startswith("import ") or
                        ("from " in l and "import" in l)]
        for line in import_lines:
            assert "ExecutionState" not in line, \
                f"PlanStateBadge must not import ExecutionState: {line}"
        # Also verify that ExecutionState is not used as a type annotation in code
        # (non-comment lines)
        code_lines = [l for l in src.splitlines()
                      if not l.strip().startswith("//") and
                      not l.strip().startswith("*")]
        for line in code_lines:
            if ": ExecutionState" in line or "as ExecutionState" in line:
                pytest.fail(f"PlanStateBadge must not use ExecutionState type annotation: {line}")

    def test_badge_uses_plan_draft_state_type(self):
        src = self.BADGE_PATH.read_text()
        assert "PlanDraftState" in src, \
            "PlanStateBadge must use PlanDraftState for its state prop"

    def test_badge_only_has_three_permitted_states(self):
        src = self.BADGE_PATH.read_text()
        # All three must be present
        for state in ("draft", "planning", "mso_review"):
            assert state in src, f"PlanStateBadge must handle state: {state}"

    def test_badge_has_forbidden_states_guard(self):
        src = self.BADGE_PATH.read_text()
        # Must have a guard for execution-adjacent states
        assert "FORBIDDEN_STATES" in src or "forbidden" in src.lower(), \
            "PlanStateBadge must have a guard for forbidden execution states"

    def test_badge_never_renders_execution_labels(self):
        src = self.BADGE_PATH.read_text()
        forbidden_labels = ["running", "executing", "completed", "approved",
                            "authorized", "live"]
        for label in forbidden_labels:
            # The label must not appear as a display string (case-insensitive)
            # Allow it inside comments about forbidden states
            lines = src.splitlines()
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue  # skip comments
                # Check it doesn't appear as a rendered label value
                if f"label: '{label}'" in line.lower() or f'label: "{label}"' in line.lower():
                    pytest.fail(
                        f"PlanStateBadge must not render '{label}' as a label"
                    )

    def test_badge_does_not_import_agent_execute(self):
        src = self.BADGE_PATH.read_text()
        assert "agent/execute" not in src
        assert "machine_operator" not in src.lower()


# ---------------------------------------------------------------------------
# TypeScript type contracts
# ---------------------------------------------------------------------------

class TestTypeScriptPlanDraftTypes:
    TYPES_PATH = UI / "lib" / "types.ts"

    def test_plan_draft_state_type_exists(self):
        src = self.TYPES_PATH.read_text()
        assert "PlanDraftState" in src

    def test_plan_draft_state_has_only_3_values(self):
        src = self.TYPES_PATH.read_text()
        # Find the PlanDraftState declaration and verify contents
        match = re.search(
            r"export type PlanDraftState\s*=\s*([^;]+);",
            src,
        )
        assert match, "PlanDraftState must be exported from types.ts"
        definition = match.group(1)
        assert "draft" in definition
        assert "planning" in definition
        assert "mso_review" in definition
        # Must NOT contain execution states
        for forbidden in ("executing", "running", "completed", "approved",
                          "authorized", "cancelled"):
            assert forbidden not in definition, \
                f"PlanDraftState must not include '{forbidden}'"

    def test_plan_draft_record_exists(self):
        src = self.TYPES_PATH.read_text()
        assert "PlanDraftRecord" in src

    def test_plan_draft_record_no_execution_fields(self):
        src = self.TYPES_PATH.read_text()
        # Find the PlanDraftRecord interface block
        match = re.search(
            r"export interface PlanDraftRecord\s*\{([^}]+)\}",
            src,
            re.DOTALL,
        )
        assert match, "PlanDraftRecord interface must exist"
        body = match.group(1)
        forbidden_fields = [
            "execution_allowed",
            "execution_status",
            "executionState",
            "used_execution",
            "policy_decision_ref",
            "governance_ref",
            "capability_token_ref",
            "authority_artifact_ref",
            "runner_ref",
            "mission_id",
            "prepared_action_id",
            "can_execute_now",
        ]
        for field in forbidden_fields:
            assert field not in body, \
                f"PlanDraftRecord must not have field: {field}"

    def test_plan_draft_response_source_is_draft_store(self):
        src = self.TYPES_PATH.read_text()
        # PlanDraftResponse source must be 'draft_store'
        assert "source: 'draft_store'" in src, \
            "PlanDraftResponse must declare source: 'draft_store'"

    def test_plan_draft_response_execution_allowed_false(self):
        src = self.TYPES_PATH.read_text()
        match = re.search(
            r"export interface PlanDraftResponse\s*\{([^}]+)\}",
            src,
            re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "execution_allowed: false" in body
        assert "used_execution: false" in body
        assert "runner_reachable_from_ui: false" in body

    def test_plan_list_response_source_is_draft_store(self):
        src = self.TYPES_PATH.read_text()
        match = re.search(
            r"export interface PlanListResponse\s*\{([^}]+)\}",
            src,
            re.DOTALL,
        )
        assert match, "PlanListResponse must exist"
        body = match.group(1)
        assert "execution_allowed: false" in body
        assert "used_execution: false" in body


# ---------------------------------------------------------------------------
# API helper contracts
# ---------------------------------------------------------------------------

class TestApiHelperContracts:
    API_PATH = UI / "lib" / "api.ts"

    def test_list_plans_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function listPlans" in src

    def test_create_plan_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function createPlan" in src

    def test_get_plan_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function getPlan" in src

    def test_update_plan_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function updatePlan" in src

    def test_transition_plan_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function transitionPlan" in src

    def test_abandon_plan_function_exists(self):
        src = self.API_PATH.read_text()
        assert "export async function abandonPlan" in src

    def test_plan_api_uses_draft_store_source(self):
        src = self.API_PATH.read_text()
        assert "'draft_store'" in src, \
            "Plan API helpers must reference source: 'draft_store'"

    def test_plan_list_unavailable_has_false_invariants(self):
        src = self.API_PATH.read_text()
        assert "PLAN_LIST_UNAVAILABLE" in src

    def test_api_helpers_not_call_agent_execute(self):
        src = self.API_PATH.read_text()
        # Find the plan-related section
        plan_section_start = src.find("Draft Store — Plan persistence")
        if plan_section_start == -1:
            plan_section_start = src.find("export async function listPlans")
        plan_section = src[plan_section_start:]
        assert "agent/execute" not in plan_section
        assert "machine_operator/execute" not in plan_section


# ---------------------------------------------------------------------------
# Next.js proxy routes existence
# ---------------------------------------------------------------------------

class TestProxyRoutesExist:
    PLANS_DIR = UI / "app" / "api" / "mso" / "plans"

    def test_plans_list_create_route_exists(self):
        assert (self.PLANS_DIR / "route.ts").exists()

    def test_plans_plan_id_route_exists(self):
        plan_id_dir = self.PLANS_DIR / "[plan_id]"
        assert (plan_id_dir / "route.ts").exists()

    def test_plans_transition_route_exists(self):
        route = self.PLANS_DIR / "[plan_id]" / "transition" / "route.ts"
        assert route.exists()

    def test_plans_abandon_route_exists(self):
        route = self.PLANS_DIR / "[plan_id]" / "abandon" / "route.ts"
        assert route.exists()

    def test_plans_audit_route_exists(self):
        route = self.PLANS_DIR / "[plan_id]" / "audit" / "route.ts"
        assert route.exists()

    def test_plan_routes_no_agent_execute_import(self):
        for route in self.PLANS_DIR.rglob("route.ts"):
            src = route.read_text()
            assert "agent/execute" not in src, \
                f"{route} must not import /api/agent/execute"
            assert "machine_operator/execute" not in src, \
                f"{route} must not call machine_operator/execute"

    def test_plan_routes_no_runner_import(self):
        for route in self.PLANS_DIR.rglob("route.ts"):
            src = route.read_text()
            assert "runner" not in src.lower() or "runner_reachable" in src, \
                f"{route} must not reference runner (except runner_reachable_from_ui)"

    def test_transition_route_does_not_create_prepare(self):
        route = self.PLANS_DIR / "[plan_id]" / "transition" / "route.ts"
        src = route.read_text()
        assert "/prepare" not in src
        assert "prepare_contract" not in src
        assert "PreparedAction" not in src


# ---------------------------------------------------------------------------
# Backend module boundary check
# ---------------------------------------------------------------------------

class TestBackendDraftStoreBoundary:
    def test_plan_model_does_not_import_prepare(self):
        import ast
        src = (REPO_ROOT / "assistant_os" / "mso" / "plan_model.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "prepared_action" not in module.lower(), \
                    f"plan_model must not import prepared_action modules: {module}"
                assert "prepare" not in module.lower() or "plan_model" in module.lower(), \
                    f"plan_model must not import prepare modules: {module}"

    def test_draft_store_does_not_import_prepare(self):
        import ast
        src = (REPO_ROOT / "assistant_os" / "mso" / "draft_store.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "prepared_action" not in module.lower(), \
                    f"draft_store must not import prepared_action modules: {module}"
                assert "authority_preparation" not in module.lower(), \
                    f"draft_store must not import authority_preparation: {module}"
