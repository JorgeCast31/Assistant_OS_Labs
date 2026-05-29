"""
Draft Store — SQLite-backed sovereign operator Plan persistence.

The Draft Store holds Plans in pre-authority states (draft, planning, mso_review).
It is NOT an authority store. It does NOT interact with:
  - MSO kernel / execution authority
  - Police gate
  - Runner
  - Token issuance
  - AuthorityArtifact creation
  - PreparedAction queue
  - Machine Operator lane

Design invariants
-----------------
  INV-PERSIST-01  Does not import from execution_proposal, authority_preparation,
                  confirmable_prepared_action, prepared_action_queue, or police modules.
  INV-PERSIST-02  Does not call MSO, Police, Runner, or any token-issuing module.
  INV-PERSIST-03  Plans in state mso_review cannot be mutated by update_plan().
  INV-PERSIST-04  Plans in state mso_review cannot be abandoned.
  INV-PERSIST-05  transition_plan() is atomic: state change and audit entry succeed
                  together or neither commits.
  INV-PERSIST-06  Any read of a record with schema_version != "1" raises
                  UnknownSchemaVersion. No silent coercion.
  INV-PERSIST-07  The SQLite file must never reside in mso_store/.
  INV-PERSIST-08  plan_id must pass prefix check (starts with "plan_") before any write.
  INV-PERSIST-09  target_actions is stored as a JSON array of strings. Never parsed
                  for capability matching or authority-chain logic.
  INV-PERSIST-10  Test isolation via ASSISTANT_OS_DRAFT_STORE_PATH env var.

D-08: update_plan() in planning state is permitted with mandatory audit log entry.
D-09: list_plans() always requires operator_seat in ALFA.
D-10: No auto-delete. Plans retained indefinitely in ALFA.
D-11: Plans in mso_review are visible as "Escalated — Pending MSO Read".
      This does NOT imply acceptance, authorization, preparation, or execution.

Sprint: #228 — Draft Persistence Implementation, no prepare.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from ..config import MEMORY_DIR
from .plan_model import (
    AUDIT_EVENTS,
    InvalidPlanId,
    InvalidTransition,
    OperatorSeatMismatch,
    PlanAuditEntry,
    PlanImmutable,
    PlanNotFound,
    PlanRecord,
    PlanUpdate,
    UnknownSchemaVersion,
    is_transition_allowed,
)

# ---------------------------------------------------------------------------
# Store path
# ---------------------------------------------------------------------------

_DRAFT_STORE_ENV = "ASSISTANT_OS_DRAFT_STORE_PATH"
DRAFT_STORE_DEFAULT: Path = MEMORY_DIR / "draft_store" / "plans.db"


def get_draft_store_path() -> Path:
    """Return the active Draft Store SQLite path.

    Reads ASSISTANT_OS_DRAFT_STORE_PATH from the environment if set
    (used for test isolation); otherwise returns the production default.
    No caching — safe to call after os.environ is patched in tests.
    """
    env_val = os.environ.get(_DRAFT_STORE_ENV, "").strip()
    if env_val:
        return Path(env_val)
    return DRAFT_STORE_DEFAULT


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_lock = threading.RLock()


def _get_connection() -> sqlite3.Connection:
    """Return a SQLite connection to the Draft Store, creating tables on first use."""
    db_path = get_draft_store_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist. Idempotent."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plan_drafts (
            plan_id          TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            intent_summary   TEXT NOT NULL,
            domain           TEXT NOT NULL,
            state            TEXT NOT NULL
                             CHECK (state IN ('draft', 'planning', 'mso_review')),
            risk_level       TEXT
                             CHECK (risk_level IN ('low','medium','high','critical')
                                    OR risk_level IS NULL),
            target_actions_json  TEXT NOT NULL DEFAULT '[]',
            notes            TEXT,
            operator_seat    TEXT NOT NULL,
            schema_version   TEXT NOT NULL DEFAULT '1',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_plan_drafts_state
            ON plan_drafts (state);

        CREATE INDEX IF NOT EXISTS idx_plan_drafts_operator_seat
            ON plan_drafts (operator_seat);

        CREATE INDEX IF NOT EXISTS idx_plan_drafts_created_at
            ON plan_drafts (created_at);

        CREATE TABLE IF NOT EXISTS plan_drafts_audit (
            audit_id      TEXT PRIMARY KEY,
            plan_id       TEXT NOT NULL,
            event         TEXT NOT NULL,
            from_state    TEXT,
            to_state      TEXT,
            operator_seat TEXT NOT NULL,
            occurred_at   TEXT NOT NULL,
            notes         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_plan_drafts_audit_plan_id
            ON plan_drafts_audit (plan_id);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_audit_id() -> str:
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"audit_{ts_ms}_{uid}"


def _row_to_record(row: sqlite3.Row) -> PlanRecord:
    """Deserialize a DB row into a PlanRecord. Raises UnknownSchemaVersion on drift."""
    schema_version = row["schema_version"]
    if schema_version != "1":
        raise UnknownSchemaVersion(
            f"plan_id={row['plan_id']} has schema_version='{schema_version}'. "
            "Fail-closed: cannot deserialize unknown schema."
        )
    try:
        target_actions = tuple(json.loads(row["target_actions_json"] or "[]"))
    except (json.JSONDecodeError, TypeError):
        target_actions = ()
    return PlanRecord(
        plan_id=row["plan_id"],
        title=row["title"],
        intent_summary=row["intent_summary"],
        domain=row["domain"],
        state=row["state"],
        operator_seat=row["operator_seat"],
        schema_version=schema_version,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        risk_level=row["risk_level"],
        target_actions=target_actions,
        notes=row["notes"],
    )


def _row_to_audit(row: sqlite3.Row) -> PlanAuditEntry:
    return PlanAuditEntry(
        audit_id=row["audit_id"],
        plan_id=row["plan_id"],
        event=row["event"],
        from_state=row["from_state"],
        to_state=row["to_state"],
        operator_seat=row["operator_seat"],
        occurred_at=row["occurred_at"],
        notes=row["notes"],
    )


def _append_audit(
    conn: sqlite3.Connection,
    plan_id: str,
    event: str,
    operator_seat: str,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """Insert an audit entry within the caller's transaction."""
    conn.execute(
        """
        INSERT INTO plan_drafts_audit
            (audit_id, plan_id, event, from_state, to_state,
             operator_seat, occurred_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _generate_audit_id(), plan_id, event, from_state, to_state,
            operator_seat, _now_iso(), notes,
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_plan(plan: PlanRecord) -> None:
    """Write a new Plan to the store.

    Raises InvalidPlanId if plan_id does not start with 'plan_'.
    Raises sqlite3.IntegrityError if plan_id already exists.
    Writes a 'created' audit entry atomically with the plan row.
    """
    if not plan.plan_id.startswith("plan_"):
        raise InvalidPlanId(f"plan_id '{plan.plan_id}' does not match plan_<ts>_<uid> format.")

    with _lock:
        conn = _get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO plan_drafts
                    (plan_id, title, intent_summary, domain, state,
                     risk_level, target_actions_json, notes,
                     operator_seat, schema_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.plan_id,
                    plan.title,
                    plan.intent_summary,
                    plan.domain,
                    plan.state,
                    plan.risk_level,
                    json.dumps(list(plan.target_actions)),
                    plan.notes,
                    plan.operator_seat,
                    plan.schema_version,
                    plan.created_at,
                    plan.updated_at,
                ),
            )
            _append_audit(conn, plan.plan_id, "created", plan.operator_seat)


def get_plan(plan_id: str, operator_seat: str) -> PlanRecord:
    """Return a Plan by ID.

    Raises PlanNotFound if no plan with that ID exists.
    Raises OperatorSeatMismatch if the plan belongs to a different operator.
    Raises UnknownSchemaVersion if schema drift is detected (fail-closed).

    D-11: Plans in mso_review are returned as-is with state='mso_review'.
    The caller is responsible for displaying them as 'Escalated — Pending MSO Read'.
    """
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()

    if row is None:
        raise PlanNotFound(f"Plan not found: {plan_id}")
    if row["operator_seat"] != operator_seat:
        raise OperatorSeatMismatch(
            f"Plan {plan_id} belongs to seat '{row['operator_seat']}', "
            f"not '{operator_seat}'."
        )
    return _row_to_record(row)


def list_plans(operator_seat: str) -> list[PlanRecord]:
    """Return all plans owned by operator_seat, in creation order.

    D-09: operator_seat is always required in ALFA. No global admin view.
    D-11: Plans in mso_review are included — labeled as escalated/pending by the caller.
    Never raises on empty result.
    """
    with _lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT * FROM plan_drafts WHERE operator_seat = ? ORDER BY created_at ASC",
            (operator_seat,),
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_plan(plan_id: str, operator_seat: str, updates: PlanUpdate) -> PlanRecord:
    """Apply non-state mutations to a Plan. Returns the updated record.

    D-08: Updates to a Plan in 'planning' state are permitted but require a
    mandatory audit log entry ('updated' event).
    Updates to 'draft' state proceed without audit.
    Updates to 'mso_review' raise PlanImmutable.

    Raises PlanNotFound, OperatorSeatMismatch, PlanImmutable, UnknownSchemaVersion.
    """
    if updates.is_empty():
        return get_plan(plan_id, operator_seat)

    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()

        if row is None:
            raise PlanNotFound(f"Plan not found: {plan_id}")
        if row["operator_seat"] != operator_seat:
            raise OperatorSeatMismatch(
                f"Plan {plan_id} belongs to seat '{row['operator_seat']}', "
                f"not '{operator_seat}'."
            )
        current_state = row["state"]
        if current_state == "mso_review":
            raise PlanImmutable(
                f"Plan {plan_id} is in mso_review state and cannot be mutated."
            )

        now = _now_iso()
        set_clauses: list[str] = ["updated_at = ?"]
        params: list = [now]

        if updates.title is not None:
            set_clauses.append("title = ?")
            params.append(updates.title)
        if updates.intent_summary is not None:
            set_clauses.append("intent_summary = ?")
            params.append(updates.intent_summary)
        if updates.domain is not None:
            set_clauses.append("domain = ?")
            params.append(updates.domain)
        if updates.risk_level is not None:
            set_clauses.append("risk_level = ?")
            params.append(updates.risk_level)
        if updates.target_actions is not None:
            set_clauses.append("target_actions_json = ?")
            params.append(json.dumps(list(updates.target_actions)))
        if updates.notes is not None:
            set_clauses.append("notes = ?")
            params.append(updates.notes)

        params.append(plan_id)

        with conn:
            conn.execute(
                f"UPDATE plan_drafts SET {', '.join(set_clauses)} WHERE plan_id = ?",
                params,
            )
            # D-08: mandatory audit log when in 'planning' state
            if current_state == "planning":
                _append_audit(conn, plan_id, "updated", operator_seat,
                              notes="Non-state mutation in planning state.")

        updated_row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    return _row_to_record(updated_row)


def transition_plan(
    plan_id: str,
    from_state: str,
    to_state: str,
    operator_seat: str,
    notes: Optional[str] = None,
) -> PlanRecord:
    """Atomically transition a Plan's state.

    The state change and audit log entry are committed together or neither commits.
    Raises InvalidTransition for any disallowed (from, to) pair.
    Raises PlanNotFound, OperatorSeatMismatch, UnknownSchemaVersion.

    D-04: Operator must explicitly initiate this call. No autonomous transitions.
    """
    if not is_transition_allowed(from_state, to_state):
        raise InvalidTransition(
            f"Transition {from_state!r} → {to_state!r} is not permitted. "
            "Allowed: draft→planning, planning→draft, planning→mso_review."
        )

    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()

        if row is None:
            raise PlanNotFound(f"Plan not found: {plan_id}")
        if row["operator_seat"] != operator_seat:
            raise OperatorSeatMismatch(
                f"Plan {plan_id} belongs to seat '{row['operator_seat']}', "
                f"not '{operator_seat}'."
            )
        current_state = row["state"]
        if current_state != from_state:
            raise InvalidTransition(
                f"Plan {plan_id} is in state '{current_state}', "
                f"not '{from_state}' as expected."
            )

        now = _now_iso()
        with conn:
            conn.execute(
                "UPDATE plan_drafts SET state = ?, updated_at = ? WHERE plan_id = ?",
                (to_state, now, plan_id),
            )
            _append_audit(
                conn, plan_id, "state_transition", operator_seat,
                from_state=from_state, to_state=to_state, notes=notes,
            )
            # Extra audit event for escalation to mso_review
            if to_state == "mso_review":
                _append_audit(
                    conn, plan_id, "escalated_to_mso_review", operator_seat,
                    from_state=from_state, to_state=to_state,
                    notes="Plan escalated to MSO for sovereign review. Frozen.",
                )

        updated_row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    return _row_to_record(updated_row)


def abandon_plan(plan_id: str, operator_seat: str) -> None:
    """Discard a plan.

    'draft' state: silently deleted, no audit entry (per D-02 resolution).
    'planning' state: deleted with mandatory audit entry ('abandoned_from_planning').
    'mso_review' state: raises PlanImmutable — create a new Plan to revise.

    Raises PlanNotFound, OperatorSeatMismatch, PlanImmutable.
    """
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)
        ).fetchone()

        if row is None:
            raise PlanNotFound(f"Plan not found: {plan_id}")
        if row["operator_seat"] != operator_seat:
            raise OperatorSeatMismatch(
                f"Plan {plan_id} belongs to seat '{row['operator_seat']}', "
                f"not '{operator_seat}'."
            )
        current_state = row["state"]
        if current_state == "mso_review":
            raise PlanImmutable(
                f"Plan {plan_id} is in mso_review and cannot be abandoned. "
                "Create a new Plan to revise the intent."
            )

        with conn:
            if current_state == "planning":
                _append_audit(
                    conn, plan_id, "abandoned_from_planning", operator_seat,
                    from_state="planning", notes="Operator discarded committed intent.",
                )
            conn.execute("DELETE FROM plan_drafts WHERE plan_id = ?", (plan_id,))


def get_audit_log(plan_id: str) -> list[PlanAuditEntry]:
    """Return all audit entries for a plan in chronological order.

    Never raises on empty result.
    """
    with _lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT * FROM plan_drafts_audit WHERE plan_id = ? ORDER BY occurred_at ASC",
            (plan_id,),
        ).fetchall()
    return [_row_to_audit(r) for r in rows]
