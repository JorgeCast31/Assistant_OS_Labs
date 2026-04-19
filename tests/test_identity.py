"""
Sprint 1 / F1: Identity + SubjectState — Unit tests.

Coverage:
  1.  PrincipalKind enum values and string representation
  2.  SubjectState enum values, is_operational, allows_read_only, blocks_all
  3.  Principal creation and predicate methods (is_human/is_agent/is_system)
  4.  Principal.to_dict() output shape
  5.  Principal immutability (frozen dataclass)
  6.  RequestIdentity basic construction
  7.  RequestIdentity.to_audit_dict() — no delegation fields
  8.  RequestIdentity.to_audit_dict() — with delegation fields
  9.  RequestIdentity.is_active() / is_delegated()
  10. Factory: human_principal() defaults and overrides
  11. Factory: agent_principal()
  12. Factory: system_principal()
  13. Factory: anonymous_human() — without session_id
  14. Factory: anonymous_human() — with session_id anchors principal id
  15. process_chat_input — audit contains _identity when identity provided
  16. process_chat_input — session carries principal_id / subject_state
  17. process_chat_input — no identity arg → backward compat (no _identity in audit)
  18. process_chat_input — identity survives pending_flow routing
  19. process_chat_input — identity survives structured-action routing (empty input)
  20. process_chat_input — subject_state value propagated as string in session
"""

import pytest

from assistant_os.identity import (
    PrincipalKind,
    SubjectState,
    Principal,
    RequestIdentity,
    human_principal,
    agent_principal,
    system_principal,
    anonymous_human,
)
from assistant_os.contracts import ChatSession, new_context_id
from assistant_os.chat_core import process_chat_input


# ---------------------------------------------------------------------------
# 1. PrincipalKind
# ---------------------------------------------------------------------------

def test_principal_kind_values():
    assert PrincipalKind.Human.value == "human"
    assert PrincipalKind.AgentInstance.value == "agent_instance"
    assert PrincipalKind.System.value == "system"


def test_principal_kind_is_str_subclass():
    # PrincipalKind inherits str so it can be used wherever a plain string is
    assert isinstance(PrincipalKind.Human, str)
    assert PrincipalKind.Human == "human"


# ---------------------------------------------------------------------------
# 2. SubjectState
# ---------------------------------------------------------------------------

def test_subject_state_values():
    assert SubjectState.Active.value == "active"
    assert SubjectState.Suspended.value == "suspended"
    assert SubjectState.Quarantined.value == "quarantined"
    assert SubjectState.Terminated.value == "terminated"


def test_subject_state_is_operational():
    assert SubjectState.Active.is_operational() is True
    assert SubjectState.Suspended.is_operational() is False
    assert SubjectState.Quarantined.is_operational() is False
    assert SubjectState.Terminated.is_operational() is False


def test_subject_state_allows_read_only():
    assert SubjectState.Active.allows_read_only() is True
    assert SubjectState.Quarantined.allows_read_only() is True
    assert SubjectState.Suspended.allows_read_only() is False
    assert SubjectState.Terminated.allows_read_only() is False


def test_subject_state_blocks_all():
    assert SubjectState.Terminated.blocks_all() is True
    assert SubjectState.Active.blocks_all() is False
    assert SubjectState.Suspended.blocks_all() is False
    assert SubjectState.Quarantined.blocks_all() is False


# ---------------------------------------------------------------------------
# 3. Principal predicates
# ---------------------------------------------------------------------------

def test_principal_is_human():
    p = Principal(kind=PrincipalKind.Human, id="human:abc", label="user")
    assert p.is_human() is True
    assert p.is_agent() is False
    assert p.is_system() is False


def test_principal_is_agent():
    p = Principal(kind=PrincipalKind.AgentInstance, id="agent-01", label="code-agent")
    assert p.is_human() is False
    assert p.is_agent() is True
    assert p.is_system() is False


def test_principal_is_system():
    p = Principal(kind=PrincipalKind.System, id="system", label="system")
    assert p.is_human() is False
    assert p.is_agent() is False
    assert p.is_system() is True


# ---------------------------------------------------------------------------
# 4. Principal.to_dict()
# ---------------------------------------------------------------------------

def test_principal_to_dict_shape():
    p = Principal(kind=PrincipalKind.Human, id="human:xyz123", label="jorge")
    d = p.to_dict()
    assert d == {"kind": "human", "id": "human:xyz123", "label": "jorge"}


def test_principal_to_dict_excludes_metadata():
    p = Principal(
        kind=PrincipalKind.Human,
        id="human:abc",
        label="user",
        metadata={"ip": "127.0.0.1"},
    )
    d = p.to_dict()
    assert "metadata" not in d


# ---------------------------------------------------------------------------
# 5. Principal immutability
# ---------------------------------------------------------------------------

def test_principal_is_frozen():
    p = Principal(kind=PrincipalKind.Human, id="human:abc", label="user")
    with pytest.raises((AttributeError, TypeError)):
        p.id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6. RequestIdentity basic construction
# ---------------------------------------------------------------------------

def test_request_identity_basic():
    p = human_principal(user_id="human:test01", label="test_user")
    ri = RequestIdentity(principal=p, subject_state=SubjectState.Active)
    assert ri.principal is p
    assert ri.subject_state == SubjectState.Active
    assert ri.session_id is None
    assert ri.spawned_by is None
    assert ri.root_principal is None


# ---------------------------------------------------------------------------
# 7. RequestIdentity.to_audit_dict() — minimal (no delegation)
# ---------------------------------------------------------------------------

def test_request_identity_to_audit_dict_minimal():
    p = human_principal(user_id="human:abc123", label="user")
    ri = RequestIdentity(
        principal=p,
        subject_state=SubjectState.Active,
        session_id="sess-001",
    )
    d = ri.to_audit_dict()
    assert d["principal"] == {"kind": "human", "id": "human:abc123", "label": "user"}
    assert d["subject_state"] == "active"
    assert d["session_id"] == "sess-001"
    assert "spawned_by" not in d
    assert "root_principal" not in d


def test_request_identity_to_audit_dict_no_session():
    p = system_principal(label="scheduler")
    ri = RequestIdentity(principal=p, subject_state=SubjectState.Active)
    d = ri.to_audit_dict()
    assert "session_id" not in d


# ---------------------------------------------------------------------------
# 8. RequestIdentity.to_audit_dict() — with delegation fields
# ---------------------------------------------------------------------------

def test_request_identity_to_audit_dict_with_delegation():
    root = human_principal(user_id="human:root", label="admin")
    spawner = agent_principal(agent_id="agent-supervisor", label="supervisor")
    child = agent_principal(agent_id="agent-worker-01", label="worker")

    ri = RequestIdentity(
        principal=child,
        subject_state=SubjectState.Active,
        session_id="sess-delegation",
        spawned_by=spawner,
        root_principal=root,
    )
    d = ri.to_audit_dict()
    assert d["spawned_by"] == {"kind": "agent_instance", "id": "agent-supervisor", "label": "supervisor"}
    assert d["root_principal"] == {"kind": "human", "id": "human:root", "label": "admin"}


# ---------------------------------------------------------------------------
# 9. RequestIdentity convenience predicates
# ---------------------------------------------------------------------------

def test_request_identity_is_active():
    ri = anonymous_human()
    assert ri.is_active() is True


def test_request_identity_not_active_when_suspended():
    p = human_principal(user_id="human:x", label="user")
    ri = RequestIdentity(principal=p, subject_state=SubjectState.Suspended)
    assert ri.is_active() is False


def test_request_identity_is_delegated():
    p = agent_principal(agent_id="agent-01", label="worker")
    spawner = system_principal()
    ri_no_delegation = RequestIdentity(principal=p, subject_state=SubjectState.Active)
    ri_delegated = RequestIdentity(principal=p, subject_state=SubjectState.Active, spawned_by=spawner)
    assert ri_no_delegation.is_delegated() is False
    assert ri_delegated.is_delegated() is True


# ---------------------------------------------------------------------------
# 10. Factory: human_principal
# ---------------------------------------------------------------------------

def test_human_principal_defaults():
    p = human_principal()
    assert p.kind == PrincipalKind.Human
    assert p.id.startswith("human:")
    assert p.label == "user"
    assert p.metadata == {}


def test_human_principal_with_user_id():
    p = human_principal(user_id="user-99", label="jorge")
    assert p.id == "user-99"
    assert p.label == "jorge"


def test_human_principal_each_call_unique_id():
    p1 = human_principal()
    p2 = human_principal()
    assert p1.id != p2.id


# ---------------------------------------------------------------------------
# 11. Factory: agent_principal
# ---------------------------------------------------------------------------

def test_agent_principal():
    p = agent_principal(agent_id="code-agent-001", label="Code Agent")
    assert p.kind == PrincipalKind.AgentInstance
    assert p.id == "code-agent-001"
    assert p.label == "Code Agent"


# ---------------------------------------------------------------------------
# 12. Factory: system_principal
# ---------------------------------------------------------------------------

def test_system_principal_defaults():
    p = system_principal()
    assert p.kind == PrincipalKind.System
    assert p.id == "system"
    assert p.label == "system"


def test_system_principal_custom_label():
    p = system_principal(label="scheduler")
    assert p.label == "scheduler"
    assert p.id == "system"  # id is always "system"


# ---------------------------------------------------------------------------
# 13. Factory: anonymous_human — without session_id
# ---------------------------------------------------------------------------

def test_anonymous_human_no_session():
    ri = anonymous_human()
    assert ri.principal.kind == PrincipalKind.Human
    assert ri.principal.id.startswith("human:")
    assert ri.subject_state == SubjectState.Active
    assert ri.session_id is None
    assert ri.spawned_by is None


# ---------------------------------------------------------------------------
# 14. Factory: anonymous_human — session_id anchors principal id
# ---------------------------------------------------------------------------

def test_anonymous_human_with_session_id():
    sess_id = "abcdef1234567890"
    ri = anonymous_human(session_id=sess_id)
    # Principal id should be scoped to the first 8 chars of the session id
    assert ri.principal.id == f"human:{sess_id[:8]}"
    assert ri.session_id == sess_id


def test_anonymous_human_same_session_same_id():
    sess_id = "mysession-xyz"
    ri1 = anonymous_human(session_id=sess_id)
    ri2 = anonymous_human(session_id=sess_id)
    assert ri1.principal.id == ri2.principal.id


# ---------------------------------------------------------------------------
# 15. process_chat_input — audit contains _identity when identity provided
# ---------------------------------------------------------------------------

def test_process_chat_input_audit_has_identity():
    identity = anonymous_human(session_id="test-session-001")
    result = process_chat_input("hola", identity=identity)
    audit = result.get("audit", {})
    assert "_identity" in audit, f"Expected '_identity' in audit, got keys: {list(audit.keys())}"
    id_data = audit["_identity"]
    assert id_data["principal"]["kind"] == "human"
    assert id_data["subject_state"] == "active"


def test_process_chat_input_audit_identity_has_session_id():
    identity = anonymous_human(session_id="sess-abc")
    result = process_chat_input("que eres?", identity=identity)
    id_data = result["audit"]["_identity"]
    assert id_data.get("session_id") == "sess-abc"


# ---------------------------------------------------------------------------
# 16. process_chat_input — session carries principal_id / subject_state
# ---------------------------------------------------------------------------

def test_process_chat_input_session_has_principal_id():
    identity = anonymous_human(session_id="sess-test")
    result = process_chat_input("hola", identity=identity)
    session = result.get("session", {})
    assert "principal_id" in session
    assert session["principal_id"] == identity.principal.id


def test_process_chat_input_session_has_subject_state():
    identity = anonymous_human()
    result = process_chat_input("modelo?", identity=identity)
    session = result.get("session", {})
    assert session.get("subject_state") == "active"


# ---------------------------------------------------------------------------
# 17. process_chat_input — backward compat: no identity → no _identity in audit
# ---------------------------------------------------------------------------

def test_process_chat_input_backward_compat_no_identity():
    """Calling without identity must not raise and must not inject _identity."""
    result = process_chat_input("hola")
    audit = result.get("audit", {})
    assert "_identity" not in audit


def test_process_chat_input_backward_compat_session_unchanged():
    """Session must not have principal_id/subject_state when identity is absent."""
    result = process_chat_input("hola")
    session = result.get("session", {})
    assert "principal_id" not in session
    assert "subject_state" not in session


# ---------------------------------------------------------------------------
# 18. process_chat_input — identity survives pending_flow routing
# ---------------------------------------------------------------------------

def test_identity_survives_pending_flow_routing():
    """Identity must be injected even when the pending_flow resolver handles the input."""
    identity = anonymous_human(session_id="sess-flow")
    ctx_id = new_context_id()
    session = ChatSession(
        pending_flow="fin_confirm",
        context_id=ctx_id,
        pending_data={"items": [{"monto": 10.0, "moneda": "USD"}]},
    )
    # "no" cancels the flow — resolver returns immediately
    result = process_chat_input("no", session=session, identity=identity)
    audit = result.get("audit", {})
    assert "_identity" in audit
    assert audit["_identity"]["principal"]["kind"] == "human"


# ---------------------------------------------------------------------------
# 19. process_chat_input — identity survives empty-input path
# ---------------------------------------------------------------------------

def test_identity_survives_empty_input_path():
    """Empty text path must also carry identity in audit."""
    identity = anonymous_human()
    result = process_chat_input("", identity=identity)
    assert result["intent"] == "empty"
    assert "_identity" in result.get("audit", {})


# ---------------------------------------------------------------------------
# 20. subject_state propagated as plain string in session
# ---------------------------------------------------------------------------

def test_subject_state_value_in_session_is_string():
    """Session dict must carry subject_state as a plain string for JSON safety."""
    identity = anonymous_human()
    result = process_chat_input("hola", identity=identity)
    subject_state_val = result["session"].get("subject_state")
    assert isinstance(subject_state_val, str)
    assert subject_state_val == "active"
