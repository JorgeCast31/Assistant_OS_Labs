"""PROVISIONAL — subject to replacement by final SovereignStateStore.

Concrete read-only SovereignStateStore backed exclusively by mso_store.

This module reads already-persisted sovereign state and derives a strict,
fail-closed runtime decision surface for backend execution checks.

KNOWN LIMITATION — token-based kill-switch detection:
  Kill-switch posture is derived by scanning ``control_plane_signals`` records
  for a fixed vocabulary of text tokens ("kill_switch", "paused", "quarantine",
  etc.) in the ``code``, ``detail``, ``source``, and ``status`` fields.  There
  is no dedicated boolean ``kill_switch_active`` field in the persisted signal
  schema.  This means:
    - A signal that happens to mention "paused" in a diagnostic detail string
      could trigger a false-positive if its ``status`` is OPEN or ACTIVE.
    - A future kill-switch signal that uses different vocabulary would be
      silently missed unless _KILL_SWITCH_TOKENS is updated.
  The implementation compensates by requiring BOTH token-match AND an explicit
  active status ("OPEN" or "ACTIVE" — empty status is NOT accepted).  Any
  uncertainty fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..contracts import now_iso
from ..storage.mso_store import query_records
from .sovereign_state_store import (
    KillSwitchState,
    SovereignDecisionReason,
    SovereignExecutionDecision,
    SovereignExecutionQuery,
    SovereignGovernanceSnapshot,
    SovereignKillSwitchSnapshot,
    SovereignStateStore,
)

_ACTIVE_RESTRICTION_STATUSES = frozenset({"ACTIVE", "EXTENDED"})
# Empty string is intentionally excluded: a signal without an explicit status
# is considered uninitialized or stale, not active.  Only records with a
# concrete active-state designation are treated as live kill-switch signals.
_ACTIVE_SIGNAL_STATUSES = frozenset({"OPEN", "ACTIVE"})
_KILL_SWITCH_TOKENS = frozenset(
    {
        "kill_switch",
        "killswitch",
        "paused",
        "pause",
        "quarantine",
        "quarantined",
    }
)


@dataclass(frozen=True, slots=True)
class _KillSwitchView:
    state: str
    active: bool
    reason: SovereignDecisionReason
    signal_ids: tuple[str, ...] = ()
    operational_mode: str = ""


class MSOSovereignStateStore(SovereignStateStore):
    """Strict read model over persisted MSO sovereign state."""

    def is_execution_allowed(
        self,
        query: SovereignExecutionQuery,
    ) -> SovereignExecutionDecision:
        try:
            critical_reason = self._validate_query(query)
            if critical_reason is not None:
                return self._blocked_decision(query=query, reason=critical_reason, kill_switch_state="unknown")

            if self._is_expired(query.expires_at):
                return self._blocked_decision(
                    query=query,
                    reason=SovereignDecisionReason(
                        code="approval_expired",
                        message="Approval artifact is expired.",
                        source="mso_store:request",
                        governance_ref=query.governance_ref,
                    ),
                    kill_switch_state="inactive",
                )

            kill_switch = self._read_kill_switch_view(
                target_domain=query.target_domain,
                target_action=self._effective_target_action(query),
                trace_id=query.trace_id,
            )
            if kill_switch.active:
                return self._blocked_decision(
                    query=query,
                    reason=kill_switch.reason,
                    kill_switch_state=kill_switch.state,
                    operational_mode=kill_switch.operational_mode,
                )

            active_restrictions = self._get_relevant_active_restrictions(query)
            if active_restrictions:
                restriction_ids = tuple(
                    str(item.get("payload", {}).get("restriction_id", "")).strip()
                    for item in active_restrictions
                    if str(item.get("payload", {}).get("restriction_id", "")).strip()
                )
                return self._blocked_decision(
                    query=query,
                    reason=SovereignDecisionReason(
                        code="restriction_active",
                        message="Active sovereign restriction blocks backend execution.",
                        source="mso_store:restrictions",
                        governance_ref=query.governance_ref,
                        restriction_ids=restriction_ids,
                    ),
                    kill_switch_state=kill_switch.state,
                    operational_mode=kill_switch.operational_mode,
                )

            return SovereignExecutionDecision(
                state="allowed",
                allowed=True,
                reason=SovereignDecisionReason(
                    code="allowed",
                    message="Sovereign state allows backend execution.",
                    source="mso_store",
                    governance_ref=query.governance_ref,
                ),
                kill_switch_state=kill_switch.state,
                operational_mode=kill_switch.operational_mode,
                checked_at=now_iso(),
                governance_ref=query.governance_ref,
                policy_decision_ref=query.policy_decision_ref,
                approval_id=query.approval_id,
            )
        except Exception:
            return self._blocked_decision(
                query=query,
                reason=SovereignDecisionReason(
                    code="state_unavailable",
                    message="Sovereign state could not be read with certainty.",
                    source="mso_store",
                    governance_ref=query.governance_ref,
                ),
                kill_switch_state="unknown",
            )

    def get_kill_switch_state(
        self,
        *,
        target_domain: str,
        target_action: str = "",
        trace_id: str = "",
    ) -> SovereignKillSwitchSnapshot:
        try:
            view = self._read_kill_switch_view(
                target_domain=target_domain,
                target_action=target_action,
                trace_id=trace_id,
            )
            return SovereignKillSwitchSnapshot(
                state=view.state,
                active=view.active,
                reason=view.reason,
                checked_at=now_iso(),
            )
        except Exception:
            return SovereignKillSwitchSnapshot(
                state="unknown",
                active=True,
                reason=SovereignDecisionReason(
                    code="state_unavailable",
                    message="Kill-switch state could not be read with certainty.",
                    source="mso_store:control_plane_signals",
                ),
                checked_at=now_iso(),
            )

    def get_reason(
        self,
        *,
        governance_ref: str = "",
        policy_decision_ref: str = "",
        approval_id: str = "",
        trace_id: str = "",
    ) -> SovereignDecisionReason:
        try:
            if not approval_id:
                return SovereignDecisionReason(
                    code="approval_missing",
                    message="Approval identifier is required.",
                    source="mso_store:request",
                    governance_ref=governance_ref,
                )
            if not policy_decision_ref or not governance_ref:
                return SovereignDecisionReason(
                    code="governance_missing",
                    message="Policy decision and governance references are required.",
                    source="mso_store:request",
                    governance_ref=governance_ref,
                )

            kill_switch = self._read_kill_switch_view(
                target_domain="MACHINE_OPERATOR",
                target_action="",
                trace_id=trace_id,
            )
            if kill_switch.active:
                return kill_switch.reason

            restrictions = self._active_restrictions_by_trace(trace_id=trace_id)
            if restrictions:
                restriction_ids = tuple(
                    str(item.get("payload", {}).get("restriction_id", "")).strip()
                    for item in restrictions
                    if str(item.get("payload", {}).get("restriction_id", "")).strip()
                )
                return SovereignDecisionReason(
                    code="restriction_active",
                    message="Active sovereign restriction is present for this trace.",
                    source="mso_store:restrictions",
                    governance_ref=governance_ref,
                    restriction_ids=restriction_ids,
                )

            return SovereignDecisionReason(
                code="allowed",
                message="No blocking sovereign reason was found in persisted state.",
                source="mso_store",
                governance_ref=governance_ref,
            )
        except Exception:
            return SovereignDecisionReason(
                code="state_unavailable",
                message="Sovereign reason could not be resolved with certainty.",
                source="mso_store",
                governance_ref=governance_ref,
            )

    def get_governance_snapshot(
        self,
        *,
        governance_ref: str,
        policy_decision_ref: str = "",
        trace_id: str = "",
        approval_id: str = "",
    ) -> SovereignGovernanceSnapshot:
        try:
            kill_switch = self._read_kill_switch_view(
                target_domain="MACHINE_OPERATOR",
                target_action="",
                trace_id=trace_id,
            )
            restrictions = self._active_restrictions_by_trace(trace_id=trace_id)
            restriction_ids = tuple(
                str(item.get("payload", {}).get("restriction_id", "")).strip()
                for item in restrictions
                if str(item.get("payload", {}).get("restriction_id", "")).strip()
            )
            active_reasons = [kill_switch.reason] if kill_switch.active else []
            if restrictions:
                active_reasons.append(
                    SovereignDecisionReason(
                        code="restriction_active",
                        message="Relevant active sovereign restrictions were found.",
                        source="mso_store:restrictions",
                        governance_ref=governance_ref,
                        restriction_ids=restriction_ids,
                    )
                )

            backing_record_kinds = list(self._matched_backing_record_kinds(trace_id=trace_id))
            if not backing_record_kinds:
                backing_record_kinds = ["restrictions", "control_plane_signals"]

            return SovereignGovernanceSnapshot(
                approval_id=approval_id,
                governance_ref=governance_ref,
                policy_decision_ref=policy_decision_ref,
                trace_id=trace_id,
                operational_mode=kill_switch.operational_mode,
                active_restriction_ids=restriction_ids,
                active_signal_ids=kill_switch.signal_ids,
                active_reasons=tuple(active_reasons),
                backing_record_kinds=tuple(backing_record_kinds),
                kill_switch_state=kill_switch.state,
            )
        except Exception:
            return SovereignGovernanceSnapshot(
                approval_id=approval_id,
                governance_ref=governance_ref,
                policy_decision_ref=policy_decision_ref,
                trace_id=trace_id,
                operational_mode="",
                active_restriction_ids=(),
                active_signal_ids=(),
                active_reasons=(
                    SovereignDecisionReason(
                        code="state_unavailable",
                        message="Governance snapshot could not be read with certainty.",
                        source="mso_store",
                        governance_ref=governance_ref,
                    ),
                ),
                backing_record_kinds=("restrictions", "control_plane_signals"),
                kill_switch_state="unknown",
            )

    def _blocked_decision(
        self,
        *,
        query: SovereignExecutionQuery,
        reason: SovereignDecisionReason,
        kill_switch_state: KillSwitchState,
        operational_mode: str = "",
    ) -> SovereignExecutionDecision:
        return SovereignExecutionDecision(
            state="blocked",
            allowed=False,
            reason=reason,
            kill_switch_state=kill_switch_state,
            operational_mode=operational_mode,
            checked_at=now_iso(),
            governance_ref=query.governance_ref,
            policy_decision_ref=query.policy_decision_ref,
            approval_id=query.approval_id,
        )

    def _validate_query(self, query: SovereignExecutionQuery) -> SovereignDecisionReason | None:
        if not query.approval_id.strip():
            return SovereignDecisionReason(
                code="approval_missing",
                message="approval_id is required for sovereign execution checks.",
                source="mso_store:request",
                governance_ref=query.governance_ref,
            )
        if not query.capability_name.strip() or not query.capability_scope.strip() or not query.expires_at.strip():
            return SovereignDecisionReason(
                code="approval_missing",
                message="Capability name, capability scope, and expires_at are required.",
                source="mso_store:request",
                governance_ref=query.governance_ref,
            )
        if not query.policy_decision_ref.strip() or not query.governance_ref.strip():
            return SovereignDecisionReason(
                code="governance_missing",
                message="policy_decision_ref and governance_ref are required.",
                source="mso_store:request",
                governance_ref=query.governance_ref,
            )
        return None

    def _effective_target_action(self, query: SovereignExecutionQuery) -> str:
        return query.target_action.strip() or query.capability_name.strip()

    def _read_kill_switch_view(
        self,
        *,
        target_domain: str,
        target_action: str,
        trace_id: str,
    ) -> _KillSwitchView:
        records = query_records(kind="control_plane_signals", limit=200)
        matching_records = [item for item in records if self._signal_matches(item.get("payload", {}), trace_id=trace_id)]
        active_records = [item for item in matching_records if self._signal_is_active(item.get("payload", {}))]
        if not active_records:
            return _KillSwitchView(
                state="inactive",
                active=False,
                reason=SovereignDecisionReason(
                    code="allowed",
                    message="No active kill-switch signal found in persisted state.",
                    source="mso_store:control_plane_signals",
                ),
            )

        signal_ids = tuple(
            str(item.get("payload", {}).get("signal_id", "")).strip()
            for item in active_records
            if str(item.get("payload", {}).get("signal_id", "")).strip()
        )
        # _derive_kill_switch_state always returns "active" when called with
        # records that already matched via _signal_matches (same token set).
        state: KillSwitchState = self._derive_kill_switch_state(active_records)
        action_label = target_action or target_domain
        return _KillSwitchView(
            state=state,
            active=True,
            reason=SovereignDecisionReason(
                code="kill_switch_active",
                message=f"Kill switch is active for {action_label}.",
                source="mso_store:control_plane_signals",
                signal_ids=signal_ids,
            ),
            signal_ids=signal_ids,
            operational_mode=state.upper(),
        )

    def _active_restrictions_by_trace(self, *, trace_id: str) -> list[dict[str, Any]]:
        records = query_records(kind="restrictions", limit=500)
        active_records = [item for item in records if self._restriction_is_active(item.get("payload", {}))]
        if trace_id:
            active_records = [item for item in active_records if str(item.get("payload", {}).get("trace_id", "")).strip() == trace_id]
        return active_records

    def _get_relevant_active_restrictions(self, query: SovereignExecutionQuery) -> list[dict[str, Any]]:
        # Always evaluate ALL active restrictions against domain+action scope.
        # trace_id on a restriction record identifies its origin, not its scope;
        # a domain-wide restriction (no trace_id) must still block any matching
        # request even when trace-specific restrictions also exist.
        effective_action = self._effective_target_action(query)
        records = query_records(kind="restrictions", limit=500)
        return [
            item
            for item in records
            if self._restriction_is_active(item.get("payload", {}))
            and self._restriction_matches_query(
                item.get("payload", {}),
                target_domain=query.target_domain,
                target_action=effective_action,
            )
        ]

    def _matched_backing_record_kinds(self, *, trace_id: str) -> tuple[str, ...]:
        matched: list[str] = []
        if query_records(kind="restrictions", limit=500):
            matched.append("restrictions")
        if query_records(kind="control_plane_signals", limit=200):
            matched.append("control_plane_signals")
        if trace_id and query_records(kind="cycles", limit=50, trace_id=trace_id):
            matched.append("cycles")
        if trace_id and query_records(kind="capabilities", limit=50, trace_id=trace_id):
            matched.append("capabilities")
        return tuple(dict.fromkeys(matched))

    def _restriction_is_active(self, payload: dict[str, Any]) -> bool:
        status = str(payload.get("status", "")).strip().upper()
        if status not in _ACTIVE_RESTRICTION_STATUSES:
            return False
        expires_at = str(payload.get("expires_at", "")).strip()
        if not expires_at:
            return True
        return not self._is_expired(expires_at)

    def _restriction_matches_query(
        self,
        payload: dict[str, Any],
        *,
        target_domain: str,
        target_action: str,
    ) -> bool:
        scope = payload.get("scope", {})
        if not isinstance(scope, dict):
            return False
        scope_domain = str(scope.get("domain", "")).strip()
        scope_action = str(scope.get("action", "")).strip()
        restriction_target = str(payload.get("target", "")).strip()

        if scope_domain and scope_domain != target_domain:
            return False
        if scope_action and scope_action not in {"*", target_action}:
            return False
        if restriction_target and restriction_target not in {target_action, "*"}:
            return False
        return True

    def _signal_matches(self, payload: dict[str, Any], *, trace_id: str) -> bool:
        if not isinstance(payload, dict):
            return False
        if trace_id:
            record_trace_id = str(payload.get("trace_id", "")).strip()
            if record_trace_id and record_trace_id != trace_id:
                return False
        haystack = " ".join(
            [
                str(payload.get("code", "")),
                str(payload.get("detail", "")),
                str(payload.get("source", "")),
                str(payload.get("status", "")),
            ]
        ).lower()
        return any(token in haystack for token in _KILL_SWITCH_TOKENS)

    def _signal_is_active(self, payload: dict[str, Any]) -> bool:
        status = str(payload.get("status", "")).strip().upper()
        return status in _ACTIVE_SIGNAL_STATUSES

    def _derive_kill_switch_state(self, records: list[dict[str, Any]]) -> str:
        haystack = " ".join(
            " ".join(
                [
                    str(item.get("payload", {}).get("code", "")),
                    str(item.get("payload", {}).get("detail", "")),
                    str(item.get("payload", {}).get("source", "")),
                    str(item.get("payload", {}).get("status", "")),
                ]
            ).lower()
            for item in records
        )
        if "quarantine" in haystack or "quarantined" in haystack:
            return "active"
        if "paused" in haystack or "pause" in haystack:
            return "active"
        if "kill_switch" in haystack or "killswitch" in haystack:
            return "active"
        # Fallback: records passed the token filter in _signal_matches, so we
        # know the kill switch is active even if the specific mode token is not
        # re-detectable here (e.g. due to case variation already lowercased).
        # Never return "unknown" when we have confirmed active records.
        return "active"

    def _is_expired(self, value: str) -> bool:
        parsed = self._parse_iso(value)
        if parsed is None:
            raise ValueError("expires_at must be a valid RFC3339 timestamp.")
        return parsed <= datetime.now(timezone.utc)

    def _parse_iso(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed
