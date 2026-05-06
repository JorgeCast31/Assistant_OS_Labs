"""
Sprint 6 — Output Control Foundation

Test classes
------------
A  TestOutputModels          — OutputFlag, InspectionResult construction + to_dict
B  TestOutputInspectorSafe   — clean outputs → safe classification
C  TestInspectorSecrets      — API keys, bearer tokens, credential assignments
D  TestInspectorPaths        — Unix and Windows absolute path detection
E  TestInspectorEnvPatterns  — env-file style KEY=VALUE detection
F  TestInspectorLongStrings  — long encoded tokens
G  TestInspectorBinary       — binary/non-printable content → invalid
H  TestInspectorRedaction    — sensitive values replaced by [REDACTED] in output
I  TestInspectorResilience   — empty input, very long input, never raises
J  TestClassificationOrder   — severity hierarchy: invalid > sensitive > warning > safe
K  TestRunnerAPIInspection   — RunnerAPI populates inspection_result on ExecutionResult
L  TestInspectionAuditEvent  — OutputSensitiveEvent emitted for non-safe output
M  TestNoLeakageInAudit      — audit events never contain output content
N  TestExecutionResultInspection — to_dict() includes inspection_result key
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


# ===========================================================================
# A — TestOutputModels
# ===========================================================================

class TestOutputModels:
    def test_output_flag_fields(self):
        from assistant_os.output.models import OutputFlag
        f = OutputFlag(flag_type="potential_secret", detail="API key", stream="stdout")
        assert f.flag_type == "potential_secret"
        assert f.detail == "API key"
        assert f.stream == "stdout"

    def test_output_flag_to_dict(self):
        from assistant_os.output.models import OutputFlag
        d = OutputFlag(flag_type="absolute_path", detail="Unix path", stream="stderr").to_dict()
        assert d["flag_type"] == "absolute_path"
        assert d["detail"] == "Unix path"
        assert d["stream"] == "stderr"
        assert "value" not in d

    def test_inspection_result_fields(self):
        from assistant_os.output.models import InspectionResult
        now = time.time()
        r = InspectionResult(
            classification="safe", flags=[], inspected_at=now,
            stdout_redacted="hello", stderr_redacted="",
        )
        assert r.classification == "safe"
        assert r.flags == []
        assert r.is_safe()
        assert not r.is_sensitive()
        assert not r.has_flags()

    def test_inspection_result_to_dict_safe_for_logs(self):
        from assistant_os.output.models import InspectionResult, OutputFlag
        flag = OutputFlag(flag_type="potential_secret", detail="Token found", stream="stdout")
        r = InspectionResult(
            classification="sensitive", flags=[flag], inspected_at=time.time(),
            stdout_redacted="out with [REDACTED]", stderr_redacted="",
        )
        d = r.to_dict()
        assert "classification" in d
        assert "flag_count" in d
        assert "flags" in d
        assert "normalized_output" in d
        assert d["flag_count"] == 1
        assert d["classification"] == "sensitive"

    def test_inspection_result_normalized_output_in_dict(self):
        from assistant_os.output.models import InspectionResult
        r = InspectionResult(
            classification="safe", flags=[], inspected_at=time.time(),
            stdout_redacted="safe output", stderr_redacted="safe err",
        )
        d = r.to_dict()
        assert d["normalized_output"]["stdout"] == "safe output"
        assert d["normalized_output"]["stderr"] == "safe err"

    def test_flag_types_convenience(self):
        from assistant_os.output.models import InspectionResult, OutputFlag
        flags = [
            OutputFlag("potential_secret", "key", "stdout"),
            OutputFlag("absolute_path", "path", "stderr"),
            OutputFlag("potential_secret", "key2", "stdout"),
        ]
        r = InspectionResult("sensitive", flags, time.time(), "", "")
        assert r.flag_types() == {"potential_secret", "absolute_path"}


# ===========================================================================
# B — TestOutputInspectorSafe
# ===========================================================================

class TestOutputInspectorSafe:
    def _inspector(self):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector()

    def test_empty_output_is_safe(self):
        r = self._inspector().inspect("", "")
        assert r.classification == "safe"
        assert not r.has_flags()

    def test_plain_text_is_safe(self):
        r = self._inspector().inspect("hello world\nTests passed: 5", "")
        assert r.classification == "safe"

    def test_numbers_and_punctuation_are_safe(self):
        r = self._inspector().inspect("result = 42\nduration: 1.5s", "")
        assert r.classification == "safe"

    def test_typical_pytest_output_is_safe(self):
        stdout = "collected 10 items\n\n...........\n\n10 passed in 0.5s"
        r = self._inspector().inspect(stdout, "")
        assert r.classification == "safe"

    def test_safe_result_has_no_flags(self):
        r = self._inspector().inspect("all good", "no issues")
        assert r.flags == []

    def test_is_safe_returns_true(self):
        r = self._inspector().inspect("clean output", "")
        assert r.is_safe() is True
        assert r.is_sensitive() is False


# ===========================================================================
# C — TestInspectorSecrets
# ===========================================================================

class TestInspectorSecrets:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_openai_api_key_detected(self):
        r = self._inspect(stdout="key=sk-abcdefghijklmnopqrstuvwxyz123456")
        assert r.classification == "sensitive"
        types = r.flag_types()
        assert "potential_secret" in types

    def test_anthropic_api_key_detected(self):
        r = self._inspect(stdout="key=sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")
        assert r.classification == "sensitive"

    def test_github_pat_detected(self):
        # ghp_ followed by exactly 36 alphanumeric chars
        r = self._inspect(stdout="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij")
        assert r.classification == "sensitive"

    def test_bearer_token_detected(self):
        r = self._inspect(stdout="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload")
        assert r.classification == "sensitive"

    def test_password_assignment_detected(self):
        r = self._inspect(stdout="password=my_super_secret_pass")
        assert r.classification == "sensitive"

    def test_api_key_assignment_detected(self):
        r = self._inspect(stdout="api_key=abcdef1234567890abcdef1234567890")
        assert r.classification == "sensitive"

    def test_access_token_detected(self):
        r = self._inspect(stdout="access_token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789")
        assert r.classification == "sensitive"

    def test_aws_access_key_detected(self):
        r = self._inspect(stdout="AKIAIOSFODNN7EXAMPLE is an AWS access key")
        assert r.classification == "sensitive"

    def test_secret_in_stderr_detected(self):
        r = self._inspect(stdout="ok", stderr="Error: token sk-abcdefghijklmnopqrstuvwxyz123 is invalid")
        assert r.classification == "sensitive"
        stderr_flags = [f for f in r.flags if f.stream == "stderr"]
        assert len(stderr_flags) > 0

    def test_classification_is_sensitive_not_warning(self):
        r = self._inspect(stdout="sk-abcdefghijklmnopqrstuvwxyz123456")
        assert r.classification == "sensitive"


# ===========================================================================
# D — TestInspectorPaths
# ===========================================================================

class TestInspectorPaths:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_unix_home_path_flagged(self):
        r = self._inspect(stdout="file written to /home/jorge/project/secret.txt")
        types = r.flag_types()
        assert "absolute_path" in types

    def test_unix_etc_path_flagged(self):
        r = self._inspect(stdout="config at /etc/passwd loaded")
        assert "absolute_path" in r.flag_types()

    def test_windows_users_path_flagged(self):
        r = self._inspect(stdout=r"file at C:\Users\jorge\AppData\Local\secret.dat")
        assert "absolute_path" in r.flag_types()

    def test_path_classification_is_warning(self):
        r = self._inspect(stdout="/home/user/workspace/data.json processed")
        # absolute_path without secrets = warning
        assert r.classification in ("warning", "sensitive")

    def test_relative_path_not_flagged(self):
        r = self._inspect(stdout="saved to ./output/result.json")
        assert "absolute_path" not in r.flag_types()


# ===========================================================================
# E — TestInspectorEnvPatterns
# ===========================================================================

class TestInspectorEnvPatterns:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_env_file_line_flagged(self):
        r = self._inspect(stdout="DATABASE_URL=postgresql://user:pass@host/db")
        assert "env_var_pattern" in r.flag_types()

    def test_env_var_pattern_is_sensitive(self):
        r = self._inspect(stdout="SECRET_KEY=supersecretvalue123")
        assert r.classification == "sensitive"

    def test_multiple_env_vars_flagged(self):
        output = "API_KEY=abc123\nDB_PASS=secret\nHOST=localhost"
        r = self._inspect(stdout=output)
        assert "env_var_pattern" in r.flag_types()


# ===========================================================================
# F — TestInspectorLongStrings
# ===========================================================================

class TestInspectorLongStrings:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_long_token_flagged(self):
        long_token = "A" * 250  # 250 chars without whitespace
        r = self._inspect(stdout=f"token={long_token}")
        assert "long_encoded_string" in r.flag_types()

    def test_short_token_not_flagged(self):
        short = "A" * 50
        r = self._inspect(stdout=f"word={short}")
        assert "long_encoded_string" not in r.flag_types()

    def test_long_token_classification_is_warning(self):
        long = "A" * 250
        r = self._inspect(stdout=long)
        # long_encoded_string without secrets = warning
        assert r.classification in ("warning", "sensitive")

    def test_long_token_redacted(self):
        long_token = "B" * 250
        r = self._inspect(stdout=f"result {long_token} end")
        assert "[REDACTED]" in r.stdout_redacted
        assert "B" * 250 not in r.stdout_redacted


# ===========================================================================
# G — TestInspectorBinary
# ===========================================================================

class TestInspectorBinary:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_binary_content_classified_invalid(self):
        binary = "normal text \x00\x01\x02\x03\x04\x05 more text"
        r = self._inspect(stdout=binary)
        assert r.classification == "invalid"

    def test_binary_in_stderr_detected(self):
        r = self._inspect(stdout="ok", stderr="data: \x00\x01\x02\x03\x04\x05 end")
        assert "binary_content" in r.flag_types()

    def test_newlines_tabs_not_binary(self):
        """Newlines, tabs, carriage returns are allowed."""
        content = "line1\nline2\ttabbed\r\nwindows"
        r = self._inspect(stdout=content)
        assert "binary_content" not in r.flag_types()

    def test_binary_overrides_warning(self):
        """binary_content produces 'invalid', higher severity than 'warning'."""
        content = "\x00\x01\x02\x03\x04\x05" + "/home/user/path"
        r = self._inspect(stdout=content)
        assert r.classification == "invalid"


# ===========================================================================
# H — TestInspectorRedaction
# ===========================================================================

class TestInspectorRedaction:
    def _inspect(self, stdout="", stderr=""):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, stderr)

    def test_api_key_redacted_in_stdout(self):
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        r = self._inspect(stdout=f"setting api_key={key} now")
        assert key not in r.stdout_redacted
        assert "[REDACTED]" in r.stdout_redacted

    def test_password_redacted(self):
        r = self._inspect(stdout="password=my_secret_pass123")
        assert "my_secret_pass123" not in r.stdout_redacted

    def test_safe_content_not_modified(self):
        r = self._inspect(stdout="test passed: 10/10", stderr="no issues")
        assert r.stdout_redacted == "test passed: 10/10"
        assert r.stderr_redacted == "no issues"

    def test_redacted_output_in_to_dict(self):
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        r = self._inspect(stdout=f"key={key}")
        d = r.to_dict()
        assert key not in d["normalized_output"]["stdout"]

    def test_to_dict_never_contains_raw_secret(self):
        import json
        r = self._inspect(stdout="password=ULTRA_SECRET_VALUE_9999")
        j = json.dumps(r.to_dict())
        assert "ULTRA_SECRET_VALUE_9999" not in j


# ===========================================================================
# I — TestInspectorResilience
# ===========================================================================

class TestInspectorResilience:
    def _inspector(self):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector()

    def test_empty_strings_no_error(self):
        r = self._inspector().inspect("", "")
        assert r.classification == "safe"

    def test_very_long_output_no_error(self):
        """Inspector must handle 100KB output without crashing."""
        big = "safe content line\n" * 6000  # ~108KB
        r = self._inspector().inspect(big, "")
        assert r.classification in ("safe", "warning", "sensitive", "invalid")

    def test_unicode_output_no_error(self):
        r = self._inspector().inspect("héllo wörld 你好世界", "")
        assert r.classification == "safe"

    def test_only_newlines_no_error(self):
        r = self._inspector().inspect("\n\n\n", "\n")
        assert r.classification == "safe"

    def test_inspect_returns_inspection_result_type(self):
        from assistant_os.output.models import InspectionResult
        r = self._inspector().inspect("output", "errors")
        assert isinstance(r, InspectionResult)

    def test_inspected_at_is_recent(self):
        before = time.time()
        r = self._inspector().inspect("hello", "")
        after = time.time()
        assert before <= r.inspected_at <= after


# ===========================================================================
# J — TestClassificationOrder
# ===========================================================================

class TestClassificationOrder:
    def _inspect(self, stdout):
        from assistant_os.output.inspector import OutputInspector
        return OutputInspector().inspect(stdout, "")

    def test_safe_is_lowest(self):
        r = self._inspect("hello world")
        assert r.classification == "safe"

    def test_warning_for_path_only(self):
        r = self._inspect("see /home/user/data.json for details")
        assert r.classification == "warning"

    def test_sensitive_for_secret(self):
        r = self._inspect("sk-abcdefghijklmnopqrstuvwxyz123456")
        assert r.classification == "sensitive"

    def test_invalid_for_binary(self):
        r = self._inspect("\x00\x01\x02\x03\x04\x05 garbage")
        assert r.classification == "invalid"

    def test_binary_overrides_secret(self):
        """If both binary and secret are present, classification is 'invalid'."""
        content = "\x00\x01\x02\x03\x04\x05 sk-abcdefghijklmnopqrstuvwxyz123456"
        r = self._inspect(content)
        assert r.classification == "invalid"

    def test_sensitive_overrides_warning(self):
        """If both secret and path are present, classification is 'sensitive'."""
        content = "sk-abcdefghijklmnopqrstuvwxyz123456 at /home/user/config"
        r = self._inspect(content)
        assert r.classification == "sensitive"


# ===========================================================================
# K — TestRunnerAPIInspection
# ===========================================================================

class TestRunnerAPIInspection:
    def _make_backend(self, stdout="", stderr="", exit_code=0):
        from assistant_os.sandbox.execution_result import ExecutionResult
        b = MagicMock()
        b.prepare.return_value = None
        b.cleanup.return_value = None
        b.execute.return_value = ExecutionResult(
            exit_code=exit_code, stdout=stdout, stderr=stderr,
            duration_ms=10, truncated=False,
        )
        return b

    def _make_plan(self, policy_id="default"):
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        return AuthorizedPlan(
            execution_id="exec-inspect-001",
            plan_id="plan-001",
            authorized_plan_hash="abc123",
            policy_id=policy_id,
        )

    def test_safe_output_has_inspection_result(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=self._make_backend(stdout="hello world")).execute(
            "print('hello')", str(tmp_path), authorized_plan=self._make_plan(),
        )
        assert result.inspection_result is not None

    def test_inspection_result_classification_safe(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=self._make_backend(stdout="Tests passed: 5")).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
        )
        assert result.inspection_result.classification == "safe"

    def test_inspection_result_sensitive_for_api_key(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(
            backend=self._make_backend(stdout="sk-abcdefghijklmnopqrstuvwxyz123456")
        ).execute("print(1)", str(tmp_path), authorized_plan=self._make_plan())
        assert result.inspection_result.classification == "sensitive"

    def test_inspection_result_in_to_dict(self, tmp_path):
        from assistant_os.sandbox.runner_api import RunnerAPI
        result = RunnerAPI(backend=self._make_backend(stdout="hello")).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
        )
        d = result.to_dict()
        assert "inspection_result" in d
        assert "classification" in d["inspection_result"]

    def test_no_inspection_result_on_internal_error(self, tmp_path):
        """Internal errors produce a placeholder result — inspection may or may not run."""
        from assistant_os.sandbox.runner_api import RunnerAPI
        b = MagicMock()
        b.prepare.return_value = None
        b.cleanup.return_value = None
        b.execute.side_effect = RuntimeError("backend exploded")
        result = RunnerAPI(backend=b).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
        )
        # Result must be returned (normalized), inspection_result may be None
        assert result is not None
        assert not result.ok


# ===========================================================================
# L — TestInspectionAuditEvent
# ===========================================================================

class TestInspectionAuditEvent:
    def _make_backend(self, stdout=""):
        from assistant_os.sandbox.execution_result import ExecutionResult
        b = MagicMock()
        b.prepare.return_value = None
        b.cleanup.return_value = None
        b.execute.return_value = ExecutionResult(
            exit_code=0, stdout=stdout, stderr="",
            duration_ms=10, truncated=False,
        )
        return b

    def _make_plan(self):
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        return AuthorizedPlan(
            execution_id="exec-audit-001",
            plan_id="plan-001",
            authorized_plan_hash="abc",
            policy_id="default",
        )

    def test_no_event_for_safe_output(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog
        from assistant_os.sandbox.runner_api import RunnerAPI
        audit = AuditLog()
        RunnerAPI(backend=self._make_backend(stdout="safe output")).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
            audit_log=audit,
        )
        sensitive_events = audit.events(AuditEventType.OUTPUT_SENSITIVE)
        assert len(sensitive_events) == 0

    def test_event_emitted_for_sensitive_output(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog
        from assistant_os.sandbox.runner_api import RunnerAPI
        audit = AuditLog()
        RunnerAPI(
            backend=self._make_backend(stdout="sk-abcdefghijklmnopqrstuvwxyz123456")
        ).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
            audit_log=audit,
        )
        events = audit.events(AuditEventType.OUTPUT_SENSITIVE)
        assert len(events) >= 1

    def test_sensitive_event_has_correct_fields(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog
        from assistant_os.sandbox.runner_api import RunnerAPI
        audit = AuditLog()
        RunnerAPI(
            backend=self._make_backend(stdout="sk-abcdefghijklmnopqrstuvwxyz123456")
        ).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
            audit_log=audit,
        )
        ev = audit.events(AuditEventType.OUTPUT_SENSITIVE)[0]
        d = ev.to_dict()
        assert d["event_type"] == "output_sensitive"
        assert "classification" in d
        assert "flag_count" in d
        assert "flag_types" in d
        assert d["flag_count"] > 0

    def test_event_emitted_for_warning_output(self, tmp_path):
        from assistant_os.sandbox.audit import AuditEventType, AuditLog
        from assistant_os.sandbox.runner_api import RunnerAPI
        audit = AuditLog()
        RunnerAPI(
            backend=self._make_backend(stdout="path: /home/user/workspace/file.txt")
        ).execute(
            "print(1)", str(tmp_path), authorized_plan=self._make_plan(),
            audit_log=audit,
        )
        events = audit.events(AuditEventType.OUTPUT_SENSITIVE)
        assert len(events) >= 1


# ===========================================================================
# M — TestNoLeakageInAudit
# ===========================================================================

class TestNoLeakageInAudit:
    def _run_with_secret(self, tmp_path, secret_value):
        from assistant_os.sandbox.audit import AuditLog
        from assistant_os.sandbox.authorized_plan import AuthorizedPlan
        from assistant_os.sandbox.execution_result import ExecutionResult
        from assistant_os.sandbox.runner_api import RunnerAPI
        b = MagicMock()
        b.prepare.return_value = None
        b.cleanup.return_value = None
        b.execute.return_value = ExecutionResult(
            exit_code=0, stdout=secret_value, stderr="", duration_ms=5, truncated=False,
        )
        plan = AuthorizedPlan(
            execution_id="exec-leak-001", plan_id="plan-001",
            authorized_plan_hash="abc", policy_id="default",
        )
        audit = AuditLog()
        RunnerAPI(backend=b).execute(
            "print(1)", str(tmp_path), authorized_plan=plan, audit_log=audit,
        )
        return audit

    def test_secret_not_in_audit_events(self, tmp_path):
        import json
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        audit = self._run_with_secret(tmp_path, secret)
        for ev in audit.events():
            j = json.dumps(ev.to_dict())
            assert secret not in j, f"Secret leaked into audit event: {ev.to_dict()['event_type']}"

    def test_password_not_in_audit_events(self, tmp_path):
        import json
        password = "password=SUPER_SECRET_PASSWORD_XYZ"
        audit = self._run_with_secret(tmp_path, password)
        for ev in audit.events():
            j = json.dumps(ev.to_dict())
            assert "SUPER_SECRET_PASSWORD_XYZ" not in j


# ===========================================================================
# N — TestExecutionResultInspection
# ===========================================================================

class TestExecutionResultInspection:
    def test_inspection_result_field_exists(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=5, truncated=False)
        assert r.inspection_result is None  # default is None

    def test_to_dict_without_inspection(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=5, truncated=False)
        d = r.to_dict()
        assert "inspection_result" not in d  # only included when set

    def test_to_dict_with_inspection(self):
        from assistant_os.output.models import InspectionResult
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult(exit_code=0, stdout="ok", stderr="", duration_ms=5, truncated=False)
        r.inspection_result = InspectionResult(
            classification="safe", flags=[], inspected_at=time.time(),
            stdout_redacted="ok", stderr_redacted="",
        )
        d = r.to_dict()
        assert "inspection_result" in d
        assert d["inspection_result"]["classification"] == "safe"

    def test_make_internal_error_has_no_inspection(self):
        from assistant_os.sandbox.execution_result import ExecutionResult
        r = ExecutionResult.make_internal_error("boom")
        assert r.inspection_result is None
