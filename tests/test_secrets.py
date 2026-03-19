"""
Tests — assistant_os/secrets (SecretInjector subsystem)

Coverage matrix
---------------
A. SecretRef contracts      — frozen dataclass, fields, to_dict              (no Docker)
B. SecretHandle lifecycle   — repr redaction, value privacy, invalidation     (no Docker)
C. EnvBundle contracts      — structure, repr redaction, cascade invalidate   (no Docker)
D. LocalEnvBackend          — env: protocol, mem: protocol, not found errors  (no Docker)
E. SecretInjector behavior  — resolve, build_env_bundle, cleanup, TTL         (no Docker)
F. Provisioning             — env file created, format, deleted after cleanup (no Docker)
G. Runner integration       — secret_refs accepted, env_file in cmd, cleanup  (no Docker)
H. Redaction / leakage      — repr safe, to_audit_dict safe, metadata clean   (no Docker)
"""

from __future__ import annotations

import os
import time

import pytest


# ===========================================================================
# A. SecretRef contracts
# ===========================================================================


class TestSecretRef:
    """SecretRef is a frozen dataclass — opaque reference, no value."""

    def _make(self, **kwargs):
        from assistant_os.secrets.secret_ref import SecretRef

        defaults = dict(
            name="API_KEY",
            ref_token="env:SOME_API_KEY",
            domain="code",
        )
        defaults.update(kwargs)
        return SecretRef(**defaults)

    def test_fields_stored_correctly(self):
        ref = self._make()
        assert ref.name == "API_KEY"
        assert ref.ref_token == "env:SOME_API_KEY"
        assert ref.domain == "code"
        assert ref.required is True

    def test_required_defaults_to_true(self):
        assert self._make().required is True

    def test_required_false_accepted(self):
        assert self._make(required=False).required is False

    def test_frozen_raises_on_mutation(self):
        ref = self._make()
        with pytest.raises((AttributeError, TypeError)):
            ref.name = "OTHER"  # type: ignore[misc]

    def test_to_dict_contains_no_value_field(self):
        d = self._make().to_dict()
        assert "name" in d
        assert "ref_token" in d
        assert "domain" in d
        assert "required" in d
        # There is no "value" field — SecretRef has no value
        assert "value" not in d

    def test_equality_based_on_fields(self):
        from assistant_os.secrets.secret_ref import SecretRef

        a = SecretRef(name="K", ref_token="env:K", domain="code")
        b = SecretRef(name="K", ref_token="env:K", domain="code")
        assert a == b


# ===========================================================================
# B. SecretHandle lifecycle
# ===========================================================================


class TestSecretHandle:
    """SecretHandle stores a value under a name-mangled private attribute."""

    def _make(self, ttl: float = 300.0) -> "object":
        from assistant_os.secrets.secret_ref import SecretHandle

        now = time.time()
        h = SecretHandle(
            handle_id="hdl-test-001",
            ref_token="env:TEST_KEY",
            name="TEST_KEY",
            plan_id="plan-001",
            execution_id="exec-001",
            domain="code",
            issued_at=now,
            expires_at=now + ttl,
        )
        h._set_value("super_secret_value")
        return h

    def test_is_valid_when_not_expired_or_invalidated(self):
        h = self._make(ttl=300.0)
        assert h.is_valid() is True

    def test_is_invalid_when_expired(self):
        h = self._make(ttl=-1.0)  # already expired
        assert h.is_valid() is False

    def test_is_invalid_after_invalidate(self):
        h = self._make()
        h.invalidate()
        assert h.is_valid() is False

    def test_consume_value_returns_set_value(self):
        h = self._make()
        assert h._consume_value() == "super_secret_value"

    def test_consume_value_raises_after_invalidate(self):
        h = self._make()
        h.invalidate()
        with pytest.raises(RuntimeError, match="invalid"):
            h._consume_value()

    def test_set_value_raises_after_invalidate(self):
        from assistant_os.secrets.secret_ref import SecretHandle

        now = time.time()
        h = SecretHandle(
            handle_id="h2", ref_token="env:X", name="X",
            plan_id="p", execution_id="e", domain="code",
            issued_at=now, expires_at=now + 300,
        )
        h._set_value("val")
        h.invalidate()
        with pytest.raises(RuntimeError, match="invalidated"):
            h._set_value("new_val")

    def test_repr_does_not_contain_value(self):
        h = self._make()
        r = repr(h)
        assert "super_secret_value" not in r
        assert "REDACTED" in r

    def test_str_does_not_contain_value(self):
        h = self._make()
        assert "super_secret_value" not in str(h)

    def test_to_audit_dict_does_not_contain_value(self):
        h = self._make()
        d = h.to_audit_dict()
        assert "value" not in d
        for v in d.values():
            assert v != "super_secret_value"

    def test_to_audit_dict_contains_metadata(self):
        h = self._make()
        d = h.to_audit_dict()
        for key in ("handle_id", "ref_token", "name", "plan_id",
                    "execution_id", "domain", "issued_at", "expires_at",
                    "invalidated"):
            assert key in d, f"to_audit_dict() missing {key!r}"

    def test_invalidate_wipes_value(self):
        h = self._make()
        h.invalidate()
        # After invalidation, internal value must be wiped — no way to read it.
        with pytest.raises(RuntimeError):
            h._consume_value()

    def test_name_mangled_attribute_not_in_normal_slots(self):
        """Value attribute should not be directly accessible as .value or ._value."""
        h = self._make()
        assert not hasattr(h, "value"), "Handle must not have a public 'value' attr"
        assert not hasattr(h, "_value"), "Handle must not have a '_value' attr"


# ===========================================================================
# C. EnvBundle contracts
# ===========================================================================


class TestEnvBundle:
    """EnvBundle carries handles but never exposes values."""

    def _make_bundle(self, n_handles: int = 2, ttl: float = 300.0):
        from assistant_os.secrets.secret_ref import EnvBundle, SecretHandle

        now = time.time()
        handles = []
        for i in range(n_handles):
            h = SecretHandle(
                handle_id=f"hdl-{i}",
                ref_token=f"env:KEY_{i}",
                name=f"KEY_{i}",
                plan_id="plan-001",
                execution_id="exec-001",
                domain="code",
                issued_at=now,
                expires_at=now + ttl,
            )
            h._set_value(f"secret_value_{i}")
            handles.append(h)

        return EnvBundle(
            bundle_id="bnd-test-001",
            execution_id="exec-001",
            plan_id="plan-001",
            handles=handles,
            issued_at=now,
            expires_at=now + ttl,
        )

    def test_is_valid_when_not_expired(self):
        assert self._make_bundle().is_valid() is True

    def test_is_invalid_when_expired(self):
        bundle = self._make_bundle(ttl=-1.0)
        assert bundle.is_valid() is False

    def test_is_invalid_after_invalidate(self):
        bundle = self._make_bundle()
        bundle.invalidate()
        assert bundle.is_valid() is False

    def test_invalidate_cascades_to_handles(self):
        bundle = self._make_bundle(n_handles=3)
        bundle.invalidate()
        for h in bundle.handles:
            assert h.invalidated is True

    def test_repr_does_not_contain_values(self):
        bundle = self._make_bundle()
        r = repr(bundle)
        for i in range(2):
            assert f"secret_value_{i}" not in r
        assert "REDACTED" in r

    def test_str_does_not_contain_values(self):
        bundle = self._make_bundle()
        s = str(bundle)
        for i in range(2):
            assert f"secret_value_{i}" not in s

    def test_to_audit_dict_does_not_contain_values(self):
        bundle = self._make_bundle()
        d = bundle.to_audit_dict()
        import json
        serialized = json.dumps(d)
        for i in range(2):
            assert f"secret_value_{i}" not in serialized

    def test_to_audit_dict_contains_metadata(self):
        d = self._make_bundle().to_audit_dict()
        for key in ("bundle_id", "execution_id", "plan_id", "secret_count",
                    "issued_at", "expires_at", "invalidated", "handles"):
            assert key in d, f"to_audit_dict() missing {key!r}"

    def test_to_audit_dict_secret_count_correct(self):
        assert self._make_bundle(n_handles=3).to_audit_dict()["secret_count"] == 3


# ===========================================================================
# D. LocalEnvBackend
# ===========================================================================


class TestLocalEnvBackend:
    """LocalEnvBackend resolves env: and mem: protocol ref_tokens."""

    def test_resolve_env_protocol(self, monkeypatch):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        monkeypatch.setenv("_TEST_AOS_SECRET", "env_secret_value")
        backend = LocalEnvBackend()
        assert backend.resolve_ref("env:_TEST_AOS_SECRET") == "env_secret_value"

    def test_resolve_mem_protocol(self):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        backend = LocalEnvBackend(memory_store={"my_key": "mem_value"})
        assert backend.resolve_ref("mem:my_key") == "mem_value"

    def test_resolve_env_not_set_raises(self):
        from assistant_os.secrets.backend import SecretNotFoundError
        from assistant_os.secrets.local_backend import LocalEnvBackend

        backend = LocalEnvBackend()
        with pytest.raises(SecretNotFoundError, match="_AOS_NONEXISTENT_VAR_"):
            backend.resolve_ref("env:_AOS_NONEXISTENT_VAR_")

    def test_resolve_mem_not_found_raises(self):
        from assistant_os.secrets.backend import SecretNotFoundError
        from assistant_os.secrets.local_backend import LocalEnvBackend

        backend = LocalEnvBackend()
        with pytest.raises(SecretNotFoundError, match="missing_key"):
            backend.resolve_ref("mem:missing_key")

    def test_resolve_unknown_protocol_raises_value_error(self):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        with pytest.raises(ValueError, match="Unrecognised ref_token protocol"):
            LocalEnvBackend().resolve_ref("vault:secret/data/foo")

    def test_resolve_empty_env_name_raises(self):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        with pytest.raises(ValueError, match="Empty env var name"):
            LocalEnvBackend().resolve_ref("env:")

    def test_resolve_empty_mem_key_raises(self):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        with pytest.raises(ValueError, match="Empty mem key"):
            LocalEnvBackend().resolve_ref("mem:")

    def test_is_available_returns_true_when_resolvable(self, monkeypatch):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        monkeypatch.setenv("_TEST_AOS_AVAIL", "yes")
        assert LocalEnvBackend().is_available("env:_TEST_AOS_AVAIL") is True

    def test_is_available_returns_false_when_missing(self):
        from assistant_os.secrets.local_backend import LocalEnvBackend

        assert LocalEnvBackend().is_available("env:_AOS_SURELY_ABSENT_9x9") is False

    def test_memory_store_is_copied_at_construction(self):
        """Mutations to the original dict after construction don't affect backend."""
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.backend import SecretNotFoundError

        store = {"key": "value"}
        backend = LocalEnvBackend(memory_store=store)
        store["key"] = "mutated"
        assert backend.resolve_ref("mem:key") == "value"


# ===========================================================================
# E. SecretInjector behavior
# ===========================================================================


class TestSecretInjector:
    """SecretInjector resolves, builds bundles, and enforces context rules."""

    def _make_injector(self, store=None):
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend

        store = store or {"api_key": "s3cret"}
        return SecretInjector(backend=LocalEnvBackend(memory_store=store))

    def _make_ref(self, name="API_KEY", token="mem:api_key", domain="code", required=True):
        from assistant_os.secrets.secret_ref import SecretRef

        return SecretRef(name=name, ref_token=token, domain=domain, required=required)

    def test_resolve_returns_valid_handle(self):
        injector = self._make_injector()
        handle = injector.resolve(self._make_ref(), plan_id="plan-001")
        assert handle.is_valid()
        assert handle.name == "API_KEY"

    def test_resolve_rejects_empty_plan_id(self):
        from assistant_os.secrets.injector import SecretResolutionError

        injector = self._make_injector()
        with pytest.raises(SecretResolutionError, match="plan_id"):
            injector.resolve(self._make_ref(), plan_id="")

    def test_resolve_rejects_whitespace_plan_id(self):
        from assistant_os.secrets.injector import SecretResolutionError

        injector = self._make_injector()
        with pytest.raises(SecretResolutionError, match="plan_id"):
            injector.resolve(self._make_ref(), plan_id="   ")

    def test_resolve_required_ref_not_found_raises(self):
        from assistant_os.secrets.injector import SecretResolutionError

        injector = self._make_injector(store={})  # empty — ref not available
        ref = self._make_ref(token="mem:missing_key", required=True)
        with pytest.raises(SecretResolutionError, match="API_KEY"):
            injector.resolve(ref, plan_id="plan-001")

    def test_resolve_optional_ref_not_found_returns_invalidated_handle(self):
        injector = self._make_injector(store={})
        ref = self._make_ref(token="mem:missing_key", required=False)
        handle = injector.resolve(ref, plan_id="plan-001")
        # Handle exists but is pre-invalidated (optional secret not available)
        assert handle.invalidated is True

    def test_build_env_bundle_requires_execution_id(self):
        from assistant_os.secrets.injector import SecretResolutionError

        injector = self._make_injector()
        with pytest.raises(SecretResolutionError, match="execution_id"):
            injector.build_env_bundle(
                [self._make_ref()], plan_id="plan-001", execution_id=""
            )

    def test_build_env_bundle_returns_valid_bundle(self):
        injector = self._make_injector()
        bundle = injector.build_env_bundle(
            [self._make_ref()], plan_id="plan-001", execution_id="exec-001"
        )
        assert bundle.is_valid()
        assert len(bundle.handles) == 1
        assert bundle.plan_id == "plan-001"
        assert bundle.execution_id == "exec-001"

    def test_cleanup_invalidates_bundle(self):
        injector = self._make_injector()
        bundle = injector.build_env_bundle(
            [self._make_ref()], plan_id="plan-001", execution_id="exec-001"
        )
        injector.cleanup(bundle)
        assert bundle.invalidated is True
        for h in bundle.handles:
            assert h.invalidated is True

    def test_handle_ttl_respected(self):
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend

        injector = SecretInjector(
            backend=LocalEnvBackend(memory_store={"k": "v"}),
            ttl_seconds=0.001,  # 1 ms — will expire almost immediately
        )
        ref = self._make_ref(token="mem:k")
        handle = injector.resolve(ref, plan_id="plan-001")
        time.sleep(0.01)  # wait for expiry
        assert handle.is_valid() is False

    def test_resolution_error_does_not_contain_raw_value(self):
        """Error messages must never include secret values."""
        from assistant_os.secrets.injector import SecretResolutionError

        injector = self._make_injector(store={"key": "SUPER_SECRET_12345"})
        ref = self._make_ref(token="mem:missing_key", required=True)
        with pytest.raises(SecretResolutionError) as exc_info:
            injector.resolve(ref, plan_id="plan-001")
        assert "SUPER_SECRET_12345" not in str(exc_info.value)


# ===========================================================================
# F. Provisioning — env file lifecycle
# ===========================================================================


class TestProvisioning:
    """Env file is created in OS temp dir and deleted by cleanup_provision."""

    def _make_bundle(self, store=None, ttl=300.0):
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend
        from assistant_os.secrets.secret_ref import SecretRef

        store = store or {"k1": "val1", "k2": "val2"}
        injector = SecretInjector(backend=LocalEnvBackend(memory_store=store))
        refs = [
            SecretRef(name="K1", ref_token="mem:k1", domain="code"),
            SecretRef(name="K2", ref_token="mem:k2", domain="code"),
        ]
        bundle = injector.build_env_bundle(
            refs, plan_id="plan-001", execution_id="exec-001"
        )
        return injector, bundle

    def test_provision_creates_file_outside_workspace(self, tmp_path):
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        try:
            assert os.path.exists(path)
            # File must NOT be under tmp_path (workspace)
            assert not path.startswith(str(tmp_path))
        finally:
            injector.cleanup_provision(path, bundle)

    def test_provision_file_has_correct_format(self):
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        try:
            content = open(path, encoding="utf-8").read()
            assert "K1=val1" in content
            assert "K2=val2" in content
        finally:
            injector.cleanup_provision(path, bundle)

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Unix file permission bits not enforced on Windows",
    )
    def test_provision_file_has_restricted_permissions(self):
        """Env file should be readable only by the owner (mode 0o600)."""
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        try:
            mode = oct(os.stat(path).st_mode)[-3:]
            assert mode == "600", f"Expected 600, got {mode}"
        finally:
            injector.cleanup_provision(path, bundle)

    def test_cleanup_provision_deletes_file(self):
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        assert os.path.exists(path)
        injector.cleanup_provision(path, bundle)
        assert not os.path.exists(path)

    def test_cleanup_provision_invalidates_bundle(self):
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        injector.cleanup_provision(path, bundle)
        assert bundle.invalidated is True

    def test_provision_rejected_for_invalid_bundle(self):
        from assistant_os.secrets.injector import SecretResolutionError

        injector, bundle = self._make_bundle()
        bundle.invalidate()
        with pytest.raises(SecretResolutionError, match="invalid or expired"):
            injector.provision_env_file(bundle)

    def test_cleanup_provision_safe_when_file_missing(self):
        """cleanup_provision must not raise if file was already deleted."""
        injector, bundle = self._make_bundle()
        path = injector.provision_env_file(bundle)
        os.unlink(path)  # manually delete first
        injector.cleanup_provision(path, bundle)  # must not raise

    def test_provision_newlines_in_value_escaped(self):
        """Newlines in secret values are escaped to prevent env-file parse errors."""
        injector, bundle = self._make_bundle(
            store={"k1": "line1\nline2", "k2": "normal"}
        )
        path = injector.provision_env_file(bundle)
        try:
            content = open(path, encoding="utf-8").read()
            # Actual newline in value must be escaped
            assert "K1=line1\\nline2" in content
        finally:
            injector.cleanup_provision(path, bundle)


# ===========================================================================
# G. Runner integration (mocked backend — no Docker)
# ===========================================================================


class TestRunnerAPISecretIntegration:
    """RunnerAPI secret injection path — all tests use a mock backend."""

    def _make_mock_backend(self):
        from unittest.mock import MagicMock
        from assistant_os.sandbox.execution_result import ExecutionResult

        ok_result = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        backend = MagicMock()
        backend.execute.return_value = ok_result
        backend.prepare.return_value = None
        backend.cleanup.return_value = None
        return backend

    def _make_injector(self, store=None):
        from assistant_os.secrets.injector import SecretInjector
        from assistant_os.secrets.local_backend import LocalEnvBackend

        return SecretInjector(
            backend=LocalEnvBackend(memory_store=store or {"api_key": "s3cr3t"})
        )

    def _make_refs(self):
        from assistant_os.secrets.secret_ref import SecretRef

        return [SecretRef(name="API_KEY", ref_token="mem:api_key", domain="code")]

    def test_runner_accepts_secret_refs_with_injector(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        plan = AuthorizedPlan(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        backend = self._make_mock_backend()
        runner = RunnerAPI(backend=backend)
        result = runner.execute(
            code="print(1)",
            workspace=str(tmp_path),
            authorized_plan=plan,
            secret_refs=self._make_refs(),
            injector=self._make_injector(),
        )
        assert result.ok

    def test_runner_passes_env_file_to_backend(self, tmp_path):
        """Backend receives a non-empty env_file path when secrets are injected."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        plan = AuthorizedPlan(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        backend = self._make_mock_backend()
        runner = RunnerAPI(backend=backend)
        runner.execute(
            code="print(1)",
            workspace=str(tmp_path),
            authorized_plan=plan,
            secret_refs=self._make_refs(),
            injector=self._make_injector(),
        )
        call_kwargs = backend.execute.call_args
        env_file_arg = call_kwargs.kwargs.get("env_file", "")
        assert env_file_arg != "", "env_file must be passed to backend when secrets injected"

    def test_env_file_deleted_after_execution(self, tmp_path):
        """Env file is deleted even when execution succeeds."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        plan = AuthorizedPlan(
            execution_id="exec-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        captured_env_file: list[str] = []

        def capturing_execute(**kwargs):
            from assistant_os.sandbox.execution_result import ExecutionResult
            captured_env_file.append(kwargs.get("env_file", ""))
            return ExecutionResult(
                exit_code=0, stdout="ok", stderr="",
                duration_ms=5, truncated=False,
            )

        from unittest.mock import MagicMock
        backend = MagicMock()
        backend.execute.side_effect = lambda **kw: capturing_execute(**kw)
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        RunnerAPI(backend=backend).execute(
            code="print(1)",
            workspace=str(tmp_path),
            authorized_plan=plan,
            secret_refs=self._make_refs(),
            injector=self._make_injector(),
        )

        assert captured_env_file, "backend.execute was not called"
        path = captured_env_file[0]
        assert path, "env_file path was empty"
        assert not os.path.exists(path), (
            f"Env file was NOT deleted after execution: {path}"
        )

    def test_env_file_deleted_even_on_execution_failure(self, tmp_path):
        """Env file is deleted in finally block even when backend raises."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        plan = AuthorizedPlan(
            execution_id="exec-002",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        captured_env_file: list[str] = []

        def raising_execute(**kwargs):
            captured_env_file.append(kwargs.get("env_file", ""))
            raise RuntimeError("backend exploded")

        from unittest.mock import MagicMock
        backend = MagicMock()
        backend.execute.side_effect = lambda **kw: raising_execute(**kw)
        backend.prepare.return_value = None
        backend.cleanup.return_value = None

        # RunnerAPI normalizes backend exceptions — returns a failure result, does NOT re-raise.
        result = RunnerAPI(backend=backend).execute(
            code="print(1)",
            workspace=str(tmp_path),
            authorized_plan=plan,
            secret_refs=self._make_refs(),
            injector=self._make_injector(),
        )
        assert not result.ok
        assert result.error is not None

        path = captured_env_file[0]
        assert not os.path.exists(path), (
            f"Env file was NOT deleted after backend failure: {path}"
        )

    def test_runner_rejects_secret_refs_without_injector(self, tmp_path):
        """secret_refs without injector raises ValueError."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        with pytest.raises(ValueError, match="injector is None"):
            RunnerAPI().execute(
                code="print(1)",
                workspace=str(tmp_path),
                secret_refs=self._make_refs(),
                injector=None,
            )

    def test_no_env_file_when_no_secrets(self, tmp_path):
        """Backend receives empty env_file when no secrets are injected."""
        from assistant_os.sandbox.runner_api import RunnerAPI

        backend = self._make_mock_backend()
        RunnerAPI(backend=backend).execute("print(1)", str(tmp_path))
        call_kwargs = backend.execute.call_args
        env_file_arg = call_kwargs.kwargs.get("env_file", "")
        assert env_file_arg == ""

    def test_secret_not_written_to_workspace(self, tmp_path):
        """After execution, workspace contains no files with secret values."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan

        plan = AuthorizedPlan(
            execution_id="exec-003",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id="default",
        )
        RunnerAPI(backend=self._make_mock_backend()).execute(
            code="print(1)",
            workspace=str(tmp_path),
            authorized_plan=plan,
            secret_refs=self._make_refs(),
            injector=self._make_injector(store={"api_key": "SHOULD_NOT_APPEAR"}),
        )
        # Walk all remaining files in workspace and check for secret value.
        for root, _, files in os.walk(str(tmp_path)):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    content = open(fpath, encoding="utf-8", errors="replace").read()
                    assert "SHOULD_NOT_APPEAR" not in content, (
                        f"Secret value found in workspace file: {fpath}"
                    )
                except OSError:
                    pass


# ===========================================================================
# H. Redaction / leakage
# ===========================================================================


class TestSecretRedaction:
    """Comprehensive checks that secret values do not leak through normal paths."""

    def _make_loaded_handle(self, value="VERY_SECRET_VALUE"):
        from assistant_os.secrets.secret_ref import SecretHandle

        now = time.time()
        h = SecretHandle(
            handle_id="hdl-leak-001",
            ref_token="mem:key",
            name="MY_KEY",
            plan_id="plan-001",
            execution_id="exec-001",
            domain="code",
            issued_at=now,
            expires_at=now + 300,
        )
        h._set_value(value)
        return h

    def test_handle_repr_redacted(self):
        h = self._make_loaded_handle()
        assert "VERY_SECRET_VALUE" not in repr(h)

    def test_handle_to_audit_dict_clean(self):
        import json
        h = self._make_loaded_handle()
        j = json.dumps(h.to_audit_dict())
        assert "VERY_SECRET_VALUE" not in j

    def test_env_bundle_repr_redacted(self):
        from assistant_os.secrets.secret_ref import EnvBundle

        now = time.time()
        h = self._make_loaded_handle("SECRET_IN_BUNDLE")
        bundle = EnvBundle(
            bundle_id="bnd-1", execution_id="e1", plan_id="p1",
            handles=[h], issued_at=now, expires_at=now + 300,
        )
        assert "SECRET_IN_BUNDLE" not in repr(bundle)

    def test_env_bundle_to_audit_dict_clean(self):
        import json
        from assistant_os.secrets.secret_ref import EnvBundle

        now = time.time()
        h = self._make_loaded_handle("AUDIT_LEAK_CHECK")
        bundle = EnvBundle(
            bundle_id="bnd-2", execution_id="e2", plan_id="p2",
            handles=[h], issued_at=now, expires_at=now + 300,
        )
        j = json.dumps(bundle.to_audit_dict())
        assert "AUDIT_LEAK_CHECK" not in j

    def test_secret_ref_to_dict_has_no_value_field(self):
        from assistant_os.secrets.secret_ref import SecretRef

        d = SecretRef(name="K", ref_token="mem:k", domain="code").to_dict()
        assert "value" not in d

    def test_container_backend_cmd_does_not_contain_values(self, tmp_path):
        """--env-file is used instead of --env KEY=VALUE so values stay out of argv."""
        from assistant_os.sandbox.container_backend import ContainerBackend

        cmd = ContainerBackend()._build_docker_cmd(
            "test-ctr", str(tmp_path), "main.py", env_file="/tmp/aos-run-test.env"
        )
        cmd_str = " ".join(cmd)
        # Env file path appears; individual KEY=VALUE pairs do not
        assert "--env-file" in cmd_str
        assert "/tmp/aos-run-test.env" in cmd_str
        # No --env KEY=VALUE pattern
        assert cmd_str.count("--env ") == 0

    def test_execution_result_to_dict_has_no_secret_fields(self):
        """ExecutionResult.to_dict() schema has no slot for secret values."""
        from assistant_os.sandbox.execution_result import ExecutionResult

        r = ExecutionResult(
            exit_code=0, stdout="ok", stderr="",
            duration_ms=10, truncated=False,
        )
        d = r.to_dict()
        for key in d:
            assert "secret" not in key.lower()
            assert "password" not in key.lower()
            assert "token" not in key.lower()
            assert "credential" not in key.lower()
