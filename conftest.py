"""
conftest.py — Root test configuration for AssistantOS.

Sets required environment variables to stub values before any test module
imports assistant_os.  This prevents config.py from raising RuntimeError
during collection for tests that do not exercise Notion or external services.

Tests that need real credentials must skip themselves or use environment
overrides via pytest marks.
"""

import os
import pytest

# ---------------------------------------------------------------------------
# Stub external credentials so config._validate_env() passes at import time.
# These values are intentionally invalid — tests must mock any real I/O.
# ---------------------------------------------------------------------------

# Only the two variables that config._validate_env() treats as required.
# Do NOT stub optional credentials (GITHUB_TOKEN, ANTHROPIC_API_KEY, etc.)
# because some tests explicitly assert behavior when those are absent.
os.environ.setdefault("NOTION_TOKEN",      "test-stub-notion-token")
os.environ.setdefault("NOTION_WORK_DB_ID", "test-stub-notion-db-id")


def _reset_runtime_state_for_test_session() -> None:
	"""Best-effort reset of cross-test global/persistent runtime state."""
	from assistant_os.context_store import clear_store
	from assistant_os.core.control_plane import _reset_state_for_tests
	from assistant_os.agents.host_agent import _reset_host_agent_state_for_tests
	from assistant_os.agents.host_audit import HOST_AUDIT_LOG
	from assistant_os.mso.capability_registry import reset_dynamic_capabilities
	from assistant_os.mso.system_state import clear_operational_mode_override
	from assistant_os.mso.task_registry import reset_task_registry
	from assistant_os.mso.trace_aggregator import reset_trace_aggregator
	from assistant_os.storage.mso_store import clear_mso_store

	reset_task_registry()
	reset_trace_aggregator()
	clear_operational_mode_override()
	reset_dynamic_capabilities()
	clear_mso_store()
	_reset_state_for_tests()
	_reset_host_agent_state_for_tests()
	HOST_AUDIT_LOG.clear()
	clear_store()


@pytest.fixture(scope="session", autouse=True)
def _session_runtime_hygiene():
	_reset_runtime_state_for_test_session()
	yield
	_reset_runtime_state_for_test_session()


@pytest.fixture(autouse=True)
def _per_test_runtime_hygiene():
	_reset_runtime_state_for_test_session()
	yield
	_reset_runtime_state_for_test_session()
