"""
Sprint 7 — Binding Final + Audit Persistence v0

Test classes
------------
A  TestMetadataPopulationSuccess     — metadata fully populated on success
B  TestMetadataPopulationFailure     — metadata populated on non-zero exit / error
C  TestMetadataPopulationAbort       — metadata populated on aborted execution
D  TestInputContractValidation       — RunnerAPI rejects incomplete / invalid plans
E  TestMetadataFieldConsistency      — every field matches actual execution data
F  TestAuditStoreBasic               — emit / events / count / read_from_disk
G  TestAuditStorePersistence         — records survive reload (new instance, same path)
H  TestAuditStoreAppendOnly          — second emit adds, never overwrites
I  TestAuditStoreSequencing          — _seq increments, order preserved
J  TestAuditStoreSafety              — no secret values; no blocked content
K  TestAuditStoreEventTypes          — all expected event types written + queryable
L  TestAuditStoreAsAuditLogDropIn    — AuditStore can replace AuditLog in RunnerAPI
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_backend(stdout="hello", stderr="", exit_code=0, error=None):
    from assistant_os.sandbox.execution_result import ExecutionResult
    b = MagicMock()
    b.prepare.return_value = None
    b.cleanup.return_value = None
    b.execute.return_value = ExecutionResult(
        exit_code=exit_code, stdout=stdout, stderr=stderr,
        duration_ms=15, truncated=False, error=error,
    )
    return b


def _make_plan(
    execution_id="exec-bind-1",
    plan_id="plan-bind-1",
    authorized_plan_hash="hash-abc123",
    policy_id="default",
    runtime_profile="python3.11",
):
    from assistant_os.sandbox.authorized_plan import AuthorizedPlan
    return AuthorizedPlan(
        execution_id=execution_id,
        plan_id=plan_id,
        authorized_plan_hash=authorized_plan_hash,
        policy_id=policy_id,
        capability_scope=["code_execution"],
        runtime_profile=runtime_profile,
    )


def _make_control_plane():
    from assistant_os.sandbox.audit import AuditLog
    from assistant_os.sandbox.execution_registry import ExecutionRegistry
    from assistant_os.sandbox.revocation import RevocationManager
    audit = AuditLog()
    registry = ExecutionRegistry()
    revmgr = RevocationManager(registry=registry, audit_log=audit)
    return audit, registry, revmgr


def _run(tmp_path, backend, plan=None, audit_log=None, registry=None, revmgr=None):
    from assistant_os.sandbox.runner_api import RunnerAPI
    return RunnerAPI(backend=backend).execute(
        "print('hi')", str(tmp_path),
        authorized_plan=plan or _make_plan(),
        audit_log=audit_log,
        registry=registry,
        revocation_manager=revmgr,
    )


# ===========================================================================
# A — TestMetadataPopulationSuccess
# ===========================================================================

class TestMetadataPopulationSuccess:
    def test_metadata_not_none(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata is not None

    def test_metadata_execution_id(self, tmp_path):
        result = _run(tmp_path, _make_backend(), plan=_make_plan(execution_id="exec-abc"))
        assert result.metadata.execution_id == "exec-abc"

    def test_metadata_plan_id(self, tmp_path):
        result = _run(tmp_path, _make_backend(), plan=_make_plan(plan_id="plan-xyz"))
        assert result.metadata.plan_id == "plan-xyz"

    def test_metadata_authorized_plan_hash(self, tmp_path):
        result = _run(tmp_path, _make_backend(), plan=_make_plan(authorized_plan_hash="hash-789"))
        assert result.metadata.authorized_plan_hash == "hash-789"

    def test_metadata_policy_id(self, tmp_path):
        result = _run(tmp_path, _make_backend(), plan=_make_plan(policy_id="strict"))
        assert result.metadata.policy_id == "strict"

    def test_metadata_runtime_profile(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata.runtime_profile == "python3.11"

    def test_metadata_backend_name(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        # MagicMock's class name contains "MagicMock"
        assert "MagicMock" in result.metadata.backend or result.metadata.backend != ""

    def test_metadata_status_completed(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=0))
        assert result.metadata.status == "completed"

    def test_metadata_termination_reason_none(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=0))
        assert result.metadata.termination_reason == "none"

    def test_metadata_duration_ms(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata.duration_ms == 15

    def test_metadata_exit_code(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=0))
        assert result.metadata.exit_code == 0

    def test_metadata_stdout_bytes(self, tmp_path):
        result = _run(tmp_path, _make_backend(stdout="hello world"))
        # stdout_bytes comes from output_record (post-policy) or raw len
        assert result.metadata.stdout_bytes == len("hello world")

    def test_metadata_no_secret_values(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        d = result.metadata.to_dict()
        sensitive = {"password", "token", "secret_value", "credential"}
        assert not sensitive.intersection({k.lower() for k in d})


# ===========================================================================
# B — TestMetadataPopulationFailure
# ===========================================================================

class TestMetadataPopulationFailure:
    def test_metadata_populated_on_nonzero_exit(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=1, stderr="error occurred"))
        assert result.metadata is not None
        assert result.metadata.exit_code == 1

    def test_metadata_status_failed_on_nonzero_exit(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=1))
        assert result.metadata.status == "failed"

    def test_metadata_termination_reason_error(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=1))
        assert result.metadata.termination_reason == "error"

    def test_metadata_populated_on_error_string(self, tmp_path):
        result = _run(tmp_path, _make_backend(exit_code=-1, error="internal runner error"))
        assert result.metadata is not None
        assert result.metadata.exit_code == -1

    def test_metadata_populated_on_timeout(self, tmp_path):
        from assistant_os.sandbox.execution_result import ExecutionResult
        b = _make_backend()
        b.execute.return_value = ExecutionResult(
            exit_code=-1, stdout="", stderr="", duration_ms=30000,
            truncated=False, timed_out=True,
        )
        result = _run(tmp_path, b)
        assert result.metadata is not None
        assert result.metadata.timed_out is True
        assert result.metadata.status == "failed"
        assert result.metadata.termination_reason == "timeout"


# ===========================================================================
# C — TestMetadataPopulationAbort
# ===========================================================================

class TestMetadataPopulationAbort:
    def test_metadata_populated_on_abort(self, tmp_path):
        """Backend returning abort error string triggers ABORTED outcome."""
        b = _make_backend(exit_code=-1, error="Execution aborted by revocation")
        result = _run(tmp_path, b)
        assert result.metadata is not None

    def test_metadata_status_aborted(self, tmp_path):
        b = _make_backend(exit_code=-1, error="Execution aborted")
        result = _run(tmp_path, b)
        assert result.metadata.status == "aborted"

    def test_metadata_termination_reason_revoked(self, tmp_path):
        b = _make_backend(exit_code=-1, error="Execution aborted")
        result = _run(tmp_path, b)
        assert result.metadata.termination_reason == "revoked"

    def test_metadata_container_id_present(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata.container_id != ""
        assert "assistantos-runner-" in result.metadata.container_id


# ===========================================================================
# D — TestInputContractValidation
# ===========================================================================

class TestInputContractValidation:
    def test_empty_execution_id_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        plan = _make_plan(execution_id="")
        with pytest.raises(ValueError, match="execution_id"):
            RunnerAPI(backend=_make_backend()).execute("code", str(tmp_path), authorized_plan=plan)

    def test_empty_plan_id_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        plan = _make_plan(plan_id="")
        with pytest.raises(ValueError, match="plan_id"):
            RunnerAPI(backend=_make_backend()).execute("code", str(tmp_path), authorized_plan=plan)

    def test_empty_authorized_plan_hash_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        plan = _make_plan(authorized_plan_hash="")
        with pytest.raises(ValueError, match="authorized_plan_hash"):
            RunnerAPI(backend=_make_backend()).execute("code", str(tmp_path), authorized_plan=plan)

    def test_unknown_policy_id_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        plan = _make_plan(policy_id="unknown-policy")
        with pytest.raises(ValueError, match="policy"):
            RunnerAPI(backend=_make_backend()).execute("code", str(tmp_path), authorized_plan=plan)

    def test_secret_refs_without_injector_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.secret_ref import SecretRef
        with pytest.raises(ValueError, match="injector"):
            RunnerAPI(backend=_make_backend()).execute(
                "code", str(tmp_path),
                authorized_plan=_make_plan(),
                secret_refs=[SecretRef(name="K", ref_token="env:K", domain="code")],
                injector=None,
            )

    def test_invalid_runtime_rejected(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        with pytest.raises(ValueError, match="Runtime"):
            RunnerAPI(backend=_make_backend()).execute(
                "code", str(tmp_path), runtime="ruby3",
            )

    def test_no_plan_allowed_for_ungoverned_execution(self, tmp_path):
        """authorized_plan=None is allowed — metadata fields will be empty strings."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=_make_backend()).execute("code", str(tmp_path))
        assert result is not None
        assert result.metadata.execution_id == ""
        assert result.metadata.plan_id == ""


# ===========================================================================
# E — TestMetadataFieldConsistency
# ===========================================================================

class TestMetadataFieldConsistency:
    def test_policy_id_matches_plan(self, tmp_path):
        result = _run(tmp_path, _make_backend(), plan=_make_plan(policy_id="strict"))
        assert result.metadata.policy_id == "strict"

    def test_runtime_profile_matches_plan(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata.runtime_profile == "python3.11"

    def test_artifact_count_zero_when_no_out(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        assert result.metadata.artifact_count == 0

    def test_artifact_count_matches_manifest(self, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (out_dir / "a.txt").write_text("a")
        (out_dir / "b.txt").write_text("b")
        result = _run(tmp_path, _make_backend())
        assert result.metadata.artifact_count == 2

    def test_stdout_bytes_correct(self, tmp_path):
        payload = "x" * 200
        result = _run(tmp_path, _make_backend(stdout=payload))
        assert result.metadata.stdout_bytes == 200

    def test_stderr_bytes_correct(self, tmp_path):
        result = _run(tmp_path, _make_backend(stderr="err" * 10))
        assert result.metadata.stderr_bytes == 30

    def test_to_dict_includes_all_new_fields(self, tmp_path):
        result = _run(tmp_path, _make_backend())
        d = result.metadata.to_dict()
        for key in ("backend", "status", "termination_reason", "container_id",
                    "stdout_bytes", "stderr_bytes", "artifact_count",
                    "authorized_plan_hash"):
            assert key in d, f"Missing field: {key}"

    def test_metadata_not_overwritten_by_caller(self, tmp_path):
        """result.metadata is set by RunnerAPI, not left to the caller."""
        result = _run(tmp_path, _make_backend())
        # The metadata must come from RunnerAPI's internal builder
        assert result.metadata.execution_id == "exec-bind-1"


# ===========================================================================
# F — TestAuditStoreBasic
# ===========================================================================

class TestAuditStoreBasic:
    def test_emit_creates_file(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        assert (tmp_path / "audit.jsonl").exists()

    def test_events_returns_emitted(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        ev = ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="completed",
        )
        store.emit(ev)
        found = store.events(AuditEventType.EXECUTION_COMPLETED)
        assert len(found) == 1

    def test_count_returns_correct_total(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        for i in range(5):
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id=f"e{i}", plan_id="p1", timestamp=float(i), status="running",
            ))
        assert store.count() == 5
        assert store.count(AuditEventType.EXECUTION_STARTED) == 5
        assert store.count(AuditEventType.EXECUTION_COMPLETED) == 0

    def test_events_filter_by_type(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent, RevocationEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        store.emit(RevocationEvent(
            event_type=AuditEventType.EXECUTION_REVOKED,
            execution_id="e1", plan_id="p1", timestamp=1.0,
        ))
        assert len(store.events(AuditEventType.EXECUTION_STARTED)) == 1
        assert len(store.events(AuditEventType.EXECUTION_REVOKED)) == 1

    def test_all_dicts_returns_dicts(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_FAILED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="failed",
        ))
        dicts = store.all_dicts()
        assert len(dicts) == 1
        assert isinstance(dicts[0], dict)
        assert dicts[0]["event_type"] == AuditEventType.EXECUTION_FAILED

    def test_read_from_disk_returns_records(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        records = store.read_from_disk()
        assert len(records) == 1
        assert records[0]["event_type"] == AuditEventType.EXECUTION_STARTED
        assert records[0]["_seq"] == 1

    def test_path_property(self, tmp_path):
        from assistant_os.sandbox.audit_store import AuditStore
        p = tmp_path / "audit.jsonl"
        store = AuditStore(p)
        assert store.path == p


# ===========================================================================
# G — TestAuditStorePersistence
# ===========================================================================

class TestAuditStorePersistence:
    def test_records_survive_reload(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"

        store1 = AuditStore(path)
        store1.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e-persist", plan_id="p1", timestamp=0.0, status="completed",
        ))
        del store1  # Simulate process end

        # New instance same path
        store2 = AuditStore(path)
        assert store2.count() == 1
        found = store2.events(AuditEventType.EXECUTION_COMPLETED)
        assert len(found) == 1
        assert found[0].event_type == AuditEventType.EXECUTION_COMPLETED

    def test_execution_id_preserved_across_reload(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"

        store1 = AuditStore(path)
        store1.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="exec-persist-id", plan_id="p1", timestamp=0.0, status="running",
        ))

        store2 = AuditStore(path)
        found = store2.events(AuditEventType.EXECUTION_STARTED)
        d = found[0].to_dict()
        assert d.get("execution_id") == "exec-persist-id"

    def test_multiple_sessions_accumulate(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"

        for session in range(3):
            store = AuditStore(path)
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_COMPLETED,
                execution_id=f"exec-{session}", plan_id="p1",
                timestamp=float(session), status="completed",
            ))

        final = AuditStore(path)
        assert final.count() == 3

    def test_seq_continues_after_reload(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"

        store1 = AuditStore(path)
        store1.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))

        store2 = AuditStore(path)
        store2.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1", timestamp=1.0, status="completed",
        ))

        records = store2.read_from_disk()
        seqs = [r["_seq"] for r in records]
        assert seqs == [1, 2]  # Sequence continues, not reset

    def test_load_existing_false_skips_file(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"

        store1 = AuditStore(path)
        store1.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))

        # load_existing=False: in-memory is empty, but file still exists
        store2 = AuditStore(path, load_existing=False)
        assert store2.count() == 0
        # File is still there
        assert path.exists()


# ===========================================================================
# H — TestAuditStoreAppendOnly
# ===========================================================================

class TestAuditStoreAppendOnly:
    def test_second_emit_adds_new_record(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        for i in range(3):
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id=f"e{i}", plan_id="p1",
                timestamp=float(i), status="running",
            ))
        assert store.count() == 3

    def test_file_grows_with_each_emit(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        sizes = []
        for i in range(4):
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id=f"e{i}", plan_id="p1",
                timestamp=float(i), status="running",
            ))
            sizes.append(path.stat().st_size)
        # Each emit should grow the file
        assert sizes == sorted(sizes)
        assert len(set(sizes)) == 4  # All different

    def test_first_records_not_modified(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="original", plan_id="p1", timestamp=0.0, status="running",
        ))
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="later", plan_id="p1", timestamp=1.0, status="completed",
        ))
        records = store.read_from_disk()
        assert records[0]["execution_id"] == "original"
        assert records[1]["execution_id"] == "later"


# ===========================================================================
# I — TestAuditStoreSequencing
# ===========================================================================

class TestAuditStoreSequencing:
    def test_seq_starts_at_one(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        records = store.read_from_disk()
        assert records[0]["_seq"] == 1

    def test_seq_increments(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        for i in range(5):
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id=f"e{i}", plan_id="p1",
                timestamp=float(i), status="running",
            ))
        records = store.read_from_disk()
        seqs = [r["_seq"] for r in records]
        assert seqs == list(range(1, 6))

    def test_written_at_is_present(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        records = store.read_from_disk()
        assert "_written_at" in records[0]
        assert isinstance(records[0]["_written_at"], float)

    def test_order_preserved(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        ids = ["first", "second", "third"]
        for eid in ids:
            store.emit(ExecutionEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                execution_id=eid, plan_id="p1", timestamp=0.0, status="running",
            ))
        records = store.read_from_disk()
        assert [r["execution_id"] for r in records] == ids

    def test_concurrent_emits_all_recorded(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        n = 50
        errors = []

        def worker(i):
            try:
                store.emit(ExecutionEvent(
                    event_type=AuditEventType.EXECUTION_STARTED,
                    execution_id=f"e{i}", plan_id="p1",
                    timestamp=float(i), status="running",
                ))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert store.count() == n
        records = store.read_from_disk()
        assert len(records) == n
        seqs = sorted(r["_seq"] for r in records)
        assert seqs == list(range(1, n + 1))


# ===========================================================================
# J — TestAuditStoreSafety
# ===========================================================================

class TestAuditStoreSafety:
    def test_no_secret_value_in_store(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, SecretAccessEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(SecretAccessEvent(
            event_type=AuditEventType.SECRET_PROVISIONED,
            secret_name="API_KEY",
            ref_token="env:ANTHROPIC_API_KEY",
            plan_id="p1",
            execution_id="e1",
            timestamp=0.0,
        ))
        content = (tmp_path / "audit.jsonl").read_text()
        # ref_token is safe (opaque reference) — the VALUE must not appear
        assert "sk-ant" not in content   # representative secret prefix
        assert "secret_value" not in content
        assert "password" not in content.lower() or "secret_name" in content

    def test_secret_name_not_value(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, SecretAccessEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(SecretAccessEvent(
            event_type=AuditEventType.SECRET_PROVISIONED,
            secret_name="MY_KEY",
            ref_token="env:MY_KEY",
            plan_id="p1",
            execution_id="e1",
            timestamp=0.0,
        ))
        records = store.read_from_disk()
        assert records[0]["secret_name"] == "MY_KEY"
        assert "value" not in records[0]  # No "value" field

    def test_output_event_no_content(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, OutputEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            stream="stdout", original_bytes=9000, retained_bytes=8192,
            policy_id="default",
        ))
        content = (tmp_path / "audit.jsonl").read_text()
        # Only metadata — not the actual stdout content
        assert "9000" in content  # original_bytes is safe
        # No large content blob
        assert len(content) < 1000

    def test_artifact_event_no_file_content(self, tmp_path):
        from assistant_os.sandbox.audit import ArtifactEvent, AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_COLLECTED,
            execution_id="e1", plan_id="p1", timestamp=0.0,
            artifact_path="out/result.json",
            size_bytes=512,
            classification="output",
            sha256="deadbeef",
        ))
        records = store.read_from_disk()
        assert "sha256" in records[0]
        assert records[0]["sha256"] == "deadbeef"
        # No "content" field
        assert "content" not in records[0]

    def test_execution_event_fields_safe(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, ExecutionEvent
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="completed",
            authorized_plan_hash="hash-abc", policy_id="default",
        ))
        records = store.read_from_disk()
        d = records[0]
        assert d["authorized_plan_hash"] == "hash-abc"
        assert d["policy_id"] == "default"
        sensitive_keys = {"value", "password", "credential", "secret_value"}
        assert not sensitive_keys.intersection({k.lower() for k in d})


# ===========================================================================
# K — TestAuditStoreEventTypes
# ===========================================================================

class TestAuditStoreEventTypes:
    def _emit_all_types(self, store):
        from assistant_os.sandbox.audit import (
            ArtifactEvent, AuditEventType, ExecutionEvent,
            OutputEvent, RevocationEvent, SecretAccessEvent,
        )
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_STARTED,
            execution_id="e1", plan_id="p1", timestamp=0.0, status="running",
        ))
        store.emit(ExecutionEvent(
            event_type=AuditEventType.EXECUTION_COMPLETED,
            execution_id="e1", plan_id="p1", timestamp=1.0, status="completed",
        ))
        store.emit(SecretAccessEvent(
            event_type=AuditEventType.SECRET_PROVISIONED,
            secret_name="K", ref_token="env:K",
            plan_id="p1", execution_id="e1", timestamp=0.5,
        ))
        store.emit(SecretAccessEvent(
            event_type=AuditEventType.SECRET_INVALIDATED,
            secret_name="K", ref_token="env:K",
            plan_id="p1", execution_id="e1", timestamp=1.5,
        ))
        store.emit(RevocationEvent(
            event_type=AuditEventType.EXECUTION_REVOKED,
            execution_id="e1", plan_id="p1", timestamp=0.8,
        ))
        store.emit(OutputEvent(
            event_type=AuditEventType.OUTPUT_TRUNCATED,
            execution_id="e1", plan_id="p1", timestamp=1.0,
            stream="stdout", original_bytes=10000, retained_bytes=8192,
            policy_id="default",
        ))
        store.emit(ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_COLLECTED,
            execution_id="e1", plan_id="p1", timestamp=1.0,
            artifact_path="out/r.txt", size_bytes=100,
        ))
        store.emit(ArtifactEvent(
            event_type=AuditEventType.ARTIFACT_REJECTED,
            execution_id="e1", plan_id="p1", timestamp=1.0,
            artifact_path="out/big.bin", size_bytes=0,
            rejection_reason="too big",
        ))

    def test_all_types_written(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        self._emit_all_types(store)
        assert store.count() == 8

    def test_all_types_queryable(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        store = AuditStore(tmp_path / "audit.jsonl")
        self._emit_all_types(store)
        assert store.count(AuditEventType.EXECUTION_STARTED) == 1
        assert store.count(AuditEventType.EXECUTION_COMPLETED) == 1
        assert store.count(AuditEventType.SECRET_PROVISIONED) == 1
        assert store.count(AuditEventType.SECRET_INVALIDATED) == 1
        assert store.count(AuditEventType.EXECUTION_REVOKED) == 1
        assert store.count(AuditEventType.OUTPUT_TRUNCATED) == 1
        assert store.count(AuditEventType.ARTIFACT_COLLECTED) == 1
        assert store.count(AuditEventType.ARTIFACT_REJECTED) == 1

    def test_all_types_persist(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"
        store1 = AuditStore(path)
        self._emit_all_types(store1)

        store2 = AuditStore(path)
        assert store2.count() == 8
        # Spot-check type filter after reload
        assert store2.count(AuditEventType.ARTIFACT_REJECTED) == 1

    def test_revocation_event_persists(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        self._emit_all_types(store)
        records = store.read_from_disk()
        types = [r["event_type"] for r in records]
        assert AuditEventType.EXECUTION_REVOKED in types


# ===========================================================================
# L — TestAuditStoreAsAuditLogDropIn
# ===========================================================================

class TestAuditStoreAsAuditLogDropIn:
    def test_store_used_as_audit_log_in_runner(self, tmp_path):
        """AuditStore can be passed as audit_log= to RunnerAPI."""
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager

        store = AuditStore(tmp_path / "audit.jsonl")
        registry = ExecutionRegistry()
        revmgr = RevocationManager(registry=registry, audit_log=store)

        _run(tmp_path, _make_backend(), audit_log=store, registry=registry, revmgr=revmgr)

        assert store.count(AuditEventType.EXECUTION_STARTED) == 1
        assert store.count(AuditEventType.EXECUTION_COMPLETED) == 1

    def test_store_events_survive_after_run(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore

        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        registry_from_revmgr = None

        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager
        registry = ExecutionRegistry()
        revmgr = RevocationManager(registry=registry, audit_log=store)
        _run(tmp_path, _make_backend(), audit_log=store, registry=registry, revmgr=revmgr)

        # New store instance — events persisted
        store2 = AuditStore(path)
        assert store2.count() >= 2  # at least started + completed

    def test_execution_event_has_plan_hash_in_store(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager

        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        registry = ExecutionRegistry()
        revmgr = RevocationManager(registry=registry, audit_log=store)

        _run(
            tmp_path,
            _make_backend(),
            plan=_make_plan(authorized_plan_hash="HASH-EXPECTED"),
            audit_log=store,
            registry=registry,
            revmgr=revmgr,
        )

        records = store.read_from_disk()
        started = [r for r in records if r["event_type"] == AuditEventType.EXECUTION_STARTED]
        assert started
        assert started[0]["authorized_plan_hash"] == "HASH-EXPECTED"

    def test_secret_events_in_store_via_runner(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType
        from assistant_os.sandbox.audit_store import AuditStore
        from assistant_os.sandbox.execution_registry import ExecutionRegistry
        from assistant_os.sandbox.revocation import RevocationManager
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        path = tmp_path / "audit.jsonl"
        store = AuditStore(path)
        registry = ExecutionRegistry()
        revmgr = RevocationManager(registry=registry, audit_log=store)

        backend_store = LocalEnvBackend(memory_store={"mykey": "DONT_PERSIST_THIS"})
        injector = SecretInjector(backend=backend_store)

        RunnerAPI(backend=_make_backend()).execute(
            "print('hi')", str(tmp_path),
            authorized_plan=_make_plan(),
            secret_refs=[SecretRef(name="MY_KEY", ref_token="mem:mykey", domain="code")],
            injector=injector,
            registry=registry,
            revocation_manager=revmgr,
            audit_log=store,
        )

        content = path.read_text()
        assert "DONT_PERSIST_THIS" not in content
        assert store.count(AuditEventType.SECRET_PROVISIONED) >= 1
        assert store.count(AuditEventType.SECRET_INVALIDATED) >= 1
