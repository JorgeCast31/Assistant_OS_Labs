"""
PlanMSOAck — sovereign read receipt: MSO acknowledges having read a Plan.

A PlanMSOAck is NOT:
  - an authorization
  - a preparation artifact
  - an execution trigger
  - a token issuance
  - a PolicyDecision
  - an AuthorityArtifact

A PlanMSOAck IS:
  - a formal record that MSO has read a Plan in mso_review state
  - produced by the operator simulating MSO read in ALPHA 1 (D-23)
  - required before POST /mso/plans/{plan_id}/prepare can proceed
  - stored in SQLite at MEMORY_DIR/prepare_store/prepare.db

Invariants (enforced by __post_init__, not negotiable)
------------------------------------------------------
  execution_allowed         = False  (always)
  used_execution            = False  (always)
  runner_reachable_from_ui  = False  (always)
  ack_status                ∈ {"acknowledged", "rejected_for_review"}

Sprint: #230 — Prepare Contract Implementation, no execution.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from ..config import MEMORY_DIR


# ---------------------------------------------------------------------------
# Store path
# ---------------------------------------------------------------------------

_PREPARE_STORE_ENV = "ASSISTANT_OS_PREPARE_STORE_PATH"
PREPARE_STORE_DEFAULT: Path = MEMORY_DIR / "prepare_store" / "prepare.db"


def get_prepare_store_path() -> Path:
    env_val = os.environ.get(_PREPARE_STORE_ENV, "").strip()
    if env_val:
        return Path(env_val)
    return PREPARE_STORE_DEFAULT


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DuplicatePlanAck(ValueError):
    """A PlanMSOAck for this plan_id already exists. One ACK per plan in ALPHA 1."""


class PlanAckNotFound(KeyError):
    """No PlanMSOAck found for the given plan_id."""


class InvalidAckStatus(ValueError):
    """ack_status is not in the permitted set: acknowledged | rejected_for_review."""


# ---------------------------------------------------------------------------
# Permitted values
# ---------------------------------------------------------------------------

_VALID_ACK_STATUSES: frozenset[str] = frozenset({"acknowledged", "rejected_for_review"})


# ---------------------------------------------------------------------------
# PlanMSOAck model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanMSOAck:
    """Immutable MSO read receipt for a Plan in mso_review state.

    ACK does not authorize. ACK does not prepare. ACK does not execute.
    ACK is a sovereign signal that MSO has read the Plan.
    """

    plan_id: str
    operator_seat: str
    ack_status: str          # "acknowledged" | "rejected_for_review"
    acknowledged_by: str     # operator identity simulating MSO read in ALPHA 1
    ack_id: str = field(default_factory=lambda: _generate_ack_id())
    acknowledged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: Optional[str] = None
    source: str = "plan_mso_ack"

    # Safety invariants — NEVER change these defaults
    execution_allowed: bool = False
    used_execution: bool = False
    runner_reachable_from_ui: bool = False

    def __post_init__(self) -> None:
        if self.ack_status not in _VALID_ACK_STATUSES:
            raise InvalidAckStatus(
                f"Invalid ack_status: '{self.ack_status}'. "
                f"Permitted: {sorted(_VALID_ACK_STATUSES)}"
            )
        if self.execution_allowed is not False:
            raise ValueError(
                "PlanMSOAck.execution_allowed must always be False. "
                "An ACK is a read receipt, not an execution authorization."
            )
        if self.used_execution is not False:
            raise ValueError(
                "PlanMSOAck.used_execution must always be False. "
                "No execution is performed to produce a PlanMSOAck."
            )
        if self.runner_reachable_from_ui is not False:
            raise ValueError(
                "PlanMSOAck.runner_reachable_from_ui must always be False."
            )

    def to_dict(self) -> dict:
        return {
            "ack_id": self.ack_id,
            "plan_id": self.plan_id,
            "operator_seat": self.operator_seat,
            "ack_status": self.ack_status,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
            "note": self.note,
            "source": self.source,
            "execution_allowed": self.execution_allowed,
            "used_execution": self.used_execution,
            "runner_reachable_from_ui": self.runner_reachable_from_ui,
        }


# ---------------------------------------------------------------------------
# ID generator
# ---------------------------------------------------------------------------

def _generate_ack_id() -> str:
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    uid = uuid4().hex[:8]
    return f"ack_{ts_ms}_{uid}"


# ---------------------------------------------------------------------------
# SQLite connection + schema
# ---------------------------------------------------------------------------

_lock = threading.RLock()


def _get_connection() -> sqlite3.Connection:
    db_path = get_prepare_store_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS plan_acks (
            ack_id           TEXT PRIMARY KEY,
            plan_id          TEXT NOT NULL UNIQUE,
            operator_seat    TEXT NOT NULL,
            ack_status       TEXT NOT NULL
                             CHECK (ack_status IN ('acknowledged', 'rejected_for_review')),
            acknowledged_by  TEXT NOT NULL,
            acknowledged_at  TEXT NOT NULL,
            note             TEXT,
            source           TEXT NOT NULL DEFAULT 'plan_mso_ack'
        );

        CREATE INDEX IF NOT EXISTS idx_plan_acks_plan_id
            ON plan_acks (plan_id);
    """)
    conn.commit()


def _row_to_ack(row: sqlite3.Row) -> PlanMSOAck:
    return PlanMSOAck(
        ack_id=row["ack_id"],
        plan_id=row["plan_id"],
        operator_seat=row["operator_seat"],
        ack_status=row["ack_status"],
        acknowledged_by=row["acknowledged_by"],
        acknowledged_at=row["acknowledged_at"],
        note=row["note"],
        source=row["source"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_ack(ack: PlanMSOAck) -> None:
    """Persist a PlanMSOAck.

    Raises DuplicatePlanAck if an ACK for this plan_id already exists.
    One ACK per plan in ALPHA 1 (D-22 conservative: reject duplicate).
    """
    with _lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO plan_acks
                        (ack_id, plan_id, operator_seat, ack_status,
                         acknowledged_by, acknowledged_at, note, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ack.ack_id,
                        ack.plan_id,
                        ack.operator_seat,
                        ack.ack_status,
                        ack.acknowledged_by,
                        ack.acknowledged_at,
                        ack.note,
                        ack.source,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() or "unique" in str(exc):
                raise DuplicatePlanAck(
                    f"A PlanMSOAck for plan_id='{ack.plan_id}' already exists. "
                    "One ACK per plan in ALPHA 1. "
                    "To change the ACK status, create a new Plan."
                ) from exc
            raise


def get_ack_for_plan(plan_id: str, operator_seat: str) -> PlanMSOAck:
    """Return the ACK for a given plan_id.

    Raises PlanAckNotFound if no ACK exists.
    """
    with _lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT * FROM plan_acks WHERE plan_id = ?", (plan_id,)
        ).fetchone()

    if row is None:
        raise PlanAckNotFound(
            f"No PlanMSOAck found for plan_id='{plan_id}'. "
            "POST /mso/plans/{plan_id}/ack to create one before calling prepare."
        )
    return _row_to_ack(row)


def list_acks_for_plan(plan_id: str) -> list[PlanMSOAck]:
    """Return all ACKs for a plan_id. Empty list if none exist."""
    with _lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT * FROM plan_acks WHERE plan_id = ? ORDER BY acknowledged_at ASC",
            (plan_id,),
        ).fetchall()
    return [_row_to_ack(r) for r in rows]
