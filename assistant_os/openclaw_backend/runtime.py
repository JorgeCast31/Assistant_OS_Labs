"""Runtime dispatch boundary for Tier A OpenClaw capabilities."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Protocol
from urllib.parse import urlparse

from . import config

_log = logging.getLogger(__name__)

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency in minimal envs
    PlaywrightTimeoutError = Exception  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]


SUPPORTED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "browser.navigate",
        "browser.snapshot",
        "browser.screenshot",
        "browser.read_visible_text",
    }
)


class RuntimeUnavailableError(RuntimeError):
    """Raised when runtime is unavailable."""


@dataclass(slots=True)
class RuntimeResult:
    status: str
    final_url: str | None
    observation: dict[str, Any]
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    consumed_budget: dict[str, int] = field(default_factory=dict)


class RuntimeDispatcher(Protocol):
    def is_available(self) -> bool: ...

    def status(self) -> dict[str, bool]: ...

    def readiness(self) -> dict[str, bool]: ...

    def execute(
        self,
        *,
        capability_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        reuse_session: bool = False,
        close_session: bool = True,
        workflow_execution_id: str = "",
        intent_id: str = "",
        correlation_id: str = "",
    ) -> RuntimeResult: ...

    def close_all(self) -> None: ...

    def cleanup_evidence(self) -> dict[str, int]: ...


class NullRuntimeDispatcher:
    """Explicitly unavailable runtime binding."""

    def is_available(self) -> bool:
        return False

    def status(self) -> dict[str, bool]:
        return {
            "runtime_available": False,
            "runtime_initialized": False,
            "runtime_usable": False,
            "runtime_importable": False,
            "playwright_available": False,
            "browser_binaries_available": False,
            "runtime_executable": False,
            "evidence_dir_writable": False,
        }

    def readiness(self) -> dict[str, bool]:
        return self.status()

    def execute(
        self,
        *,
        capability_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        reuse_session: bool = False,
        close_session: bool = True,
        workflow_execution_id: str = "",
        intent_id: str = "",
        correlation_id: str = "",
    ) -> RuntimeResult:
        raise RuntimeUnavailableError(
            f"OpenClaw runtime unavailable for capability '{capability_name}'."
        )

    def close_all(self) -> None:
        return

    def cleanup_evidence(self) -> dict[str, int]:
        return {"deleted_files": 0}


@dataclass(slots=True)
class _RuntimeSession:
    context: Any
    page: Any
    created_at: float


class PlaywrightRuntimeDispatcher:
    """Real Tier A runtime dispatcher backed by Playwright."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._playwright = None
        self._browser = None
        self._sessions: dict[str, _RuntimeSession] = {}
        self._evidence_dir = config.OPENCLAW_EVIDENCE_DIR
        self._last_init_error = ""
        self._ensure_evidence_dir_exists()
        _log.info("openclaw_runtime_initialized evidence_dir=%s", self._evidence_dir)

    def is_available(self) -> bool:
        return self.readiness()["runtime_usable"]

    def status(self) -> dict[str, bool]:
        runtime_importable = sync_playwright is not None
        evidence_dir_writable = self._is_evidence_dir_writable()
        return {
            "runtime_available": runtime_importable,
            "runtime_initialized": self._browser is not None,
            "runtime_usable": runtime_importable and evidence_dir_writable,
            "runtime_importable": runtime_importable,
            "playwright_available": runtime_importable,
            "browser_binaries_available": False,
            "runtime_executable": False,
            "evidence_dir_writable": evidence_dir_writable,
        }

    def readiness(self) -> dict[str, bool]:
        with self._lock:
            runtime_importable = sync_playwright is not None
            evidence_dir_writable = self._is_evidence_dir_writable()
            browser_binaries_available = False
            runtime_executable = False

            if runtime_importable and evidence_dir_writable:
                try:
                    self._ensure_runtime_locked()
                    browser_binaries_available = self._browser is not None
                    runtime_executable = self._probe_page_execution_locked()
                except RuntimeUnavailableError:
                    browser_binaries_available = False
                    runtime_executable = False

            runtime_usable = (
                runtime_importable
                and evidence_dir_writable
                and browser_binaries_available
                and runtime_executable
            )
            return {
                "runtime_available": runtime_importable,
                "runtime_initialized": self._browser is not None,
                "runtime_usable": runtime_usable,
                "runtime_importable": runtime_importable,
                "playwright_available": runtime_importable,
                "browser_binaries_available": browser_binaries_available,
                "runtime_executable": runtime_executable,
                "evidence_dir_writable": evidence_dir_writable,
            }

    def close_all(self) -> None:
        with self._lock:
            session_count = len(self._sessions)
            for session_id in list(self._sessions.keys()):
                self._close_session_locked(session_id)
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            _log.info("openclaw_runtime_closed sessions=%s", session_count)

    def cleanup_evidence(self) -> dict[str, int]:
        with self._lock:
            result = self._cleanup_evidence_locked()
            if result.get("deleted_files", 0) > 0:
                _log.info("openclaw_evidence_cleanup deleted_files=%s", result["deleted_files"])
            return result

    def execute(
        self,
        *,
        capability_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        reuse_session: bool = False,
        close_session: bool = True,
        workflow_execution_id: str = "",
        intent_id: str = "",
        correlation_id: str = "",
    ) -> RuntimeResult:
        if capability_name not in SUPPORTED_CAPABILITIES:
            raise ValueError(f"Unsupported capability: {capability_name}")
        url = _validate_url(arguments)
        timeout_ms = max(int(timeout_seconds * 1000), 1)

        with self._lock:
            self._ensure_runtime_locked()
            session_key = workflow_execution_id.strip() if reuse_session and workflow_execution_id.strip() else ""
            if session_key:
                session = self._sessions.get(session_key)
                if session is None:
                    session = self._new_session_locked()
                    self._sessions[session_key] = session
                ephemeral = False
            else:
                session = self._new_session_locked()
                ephemeral = True

        started = time.perf_counter()
        try:
            result = self._execute_with_session(
                session=session,
                capability_name=capability_name,
                url=url,
                timeout_ms=timeout_ms,
                intent_id=intent_id,
                workflow_execution_id=workflow_execution_id,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            result.consumed_budget.setdefault("steps", 1)
            result.consumed_budget["duration_ms"] = max(
                int(result.consumed_budget.get("duration_ms", elapsed_ms)),
                elapsed_ms,
            )
            result.consumed_budget["side_effects"] = 0
            result.consumed_budget["output_bytes"] = max(
                int(result.consumed_budget.get("output_bytes", 0)),
                _estimate_output_bytes(result),
            )
            return result
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        finally:
            with self._lock:
                if ephemeral:
                    self._close_ephemeral_session_locked(session)
                elif close_session and session_key:
                    self._close_session_locked(session_key)

    def _execute_with_session(
        self,
        *,
        session: _RuntimeSession,
        capability_name: str,
        url: str,
        timeout_ms: int,
        intent_id: str,
        workflow_execution_id: str,
    ) -> RuntimeResult:
        page = session.page
        page.set_default_timeout(timeout_ms)
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        final_url = page.url if isinstance(page.url, str) and page.url else url

        status_code = None
        if response is not None:
            try:
                status_code = int(response.status)
            except Exception:
                status_code = None

        if capability_name == "browser.navigate":
            return RuntimeResult(
                status="ok",
                final_url=final_url,
                observation={
                    "summary": "Navigation completed",
                    "detail": f"Navigated to {final_url}",
                    "structured_data": {
                        "http_status": status_code,
                    },
                },
            )

        if capability_name == "browser.snapshot":
            html_content = page.content()
            preview, truncated = _truncate_utf8(html_content, 2048)
            evidence_ref = self._write_evidence(
                suffix=".html",
                payload=html_content.encode("utf-8"),
                evidence_type="dom_snapshot",
                media_type="text/html",
                intent_id=intent_id,
                workflow_execution_id=workflow_execution_id,
            )
            return RuntimeResult(
                status="ok",
                final_url=final_url,
                observation={
                    "summary": "DOM snapshot captured",
                    "detail": "Captured page HTML snapshot",
                    "structured_data": {
                        "html_preview": preview,
                        "is_truncated": truncated,
                        "snapshot_ref_id": evidence_ref["ref_id"],
                        "http_status": status_code,
                    },
                },
                evidence_refs=[evidence_ref],
            )

        if capability_name == "browser.screenshot":
            screenshot_bytes = page.screenshot(full_page=True, type="png", timeout=timeout_ms)
            evidence_ref = self._write_evidence(
                suffix=".png",
                payload=screenshot_bytes,
                evidence_type="image",
                media_type="image/png",
                intent_id=intent_id,
                workflow_execution_id=workflow_execution_id,
            )
            return RuntimeResult(
                status="ok",
                final_url=final_url,
                observation={
                    "summary": "Screenshot captured",
                    "detail": "Captured full-page screenshot",
                    "structured_data": {
                        "screenshot_ref_id": evidence_ref["ref_id"],
                        "byte_size": len(screenshot_bytes),
                        "http_status": status_code,
                    },
                },
                evidence_refs=[evidence_ref],
            )

        visible_text = page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
        if not isinstance(visible_text, str):
            visible_text = ""
        bounded_text, truncated = _truncate_utf8(visible_text, 2048)
        return RuntimeResult(
            status="ok",
            final_url=final_url,
            observation={
                "summary": "Visible text extracted",
                "detail": "Extracted visible text from current document",
                "structured_data": {
                    "visible_text": bounded_text,
                    "is_truncated": truncated,
                    "http_status": status_code,
                },
            },
        )

    def _probe_runtime(self) -> bool:
        with self._lock:
            try:
                self._ensure_runtime_locked()
                return True
            except RuntimeUnavailableError:
                return False

    def _ensure_runtime_locked(self) -> None:
        if self._browser is not None:
            return
        if sync_playwright is None:
            self._last_init_error = "playwright_not_installed"
            _log.error("openclaw_runtime_init_failed reason=playwright_not_installed")
            raise RuntimeUnavailableError("Playwright runtime is not installed.")
        try:
            _log.info("openclaw_runtime_init_start")
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._last_init_error = ""
            _log.info("openclaw_runtime_init_success")
        except Exception as exc:
            self._last_init_error = str(exc)
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._browser = None
            _log.error("openclaw_runtime_init_failed reason=browser_launch_error detail=%s", exc)
            raise RuntimeUnavailableError("Unable to initialize Playwright runtime.") from exc

    def _probe_page_execution_locked(self) -> bool:
        if self._browser is None:
            return False
        try:
            context = self._browser.new_context(ignore_https_errors=False)
            page = context.new_page()
            page.goto("about:blank", wait_until="domcontentloaded", timeout=2000)
            context.close()
            return True
        except Exception:
            return False

    def _new_session_locked(self) -> _RuntimeSession:
        assert self._browser is not None
        context = self._browser.new_context(ignore_https_errors=False)
        page = context.new_page()
        return _RuntimeSession(context=context, page=page, created_at=time.time())

    def _close_session_locked(self, session_key: str) -> None:
        session = self._sessions.pop(session_key, None)
        if session is None:
            return
        try:
            session.context.close()
        except Exception:
            pass

    def _close_ephemeral_session_locked(self, session: _RuntimeSession) -> None:
        try:
            session.context.close()
        except Exception:
            pass

    def _write_evidence(
        self,
        *,
        suffix: str,
        payload: bytes,
        evidence_type: str,
        media_type: str,
        intent_id: str = "",
        workflow_execution_id: str = "",
    ) -> dict[str, str]:
        ref_id = _build_evidence_ref_id(intent_id=intent_id, workflow_execution_id=workflow_execution_id)
        file_path = self._evidence_dir / f"{ref_id}{suffix}"
        file_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        try:
            uri = file_path.as_uri()
        except ValueError:
            # Windows host running Linux-style paths: construct manually
            uri = f"file://{file_path.as_posix()}"
        return {
            "ref_id": ref_id,
            "evidence_type": evidence_type,
            "uri": uri,
            "media_type": media_type,
            "digest": f"sha256:{digest}",
            "description": "OpenClaw runtime evidence",
        }

    def _ensure_evidence_dir_exists(self) -> None:
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

    def _is_evidence_dir_writable(self) -> bool:
        try:
            self._ensure_evidence_dir_exists()
            probe = self._evidence_dir / f".probe-{uuid.uuid4().hex}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def _cleanup_evidence_locked(self) -> dict[str, int]:
        deleted_files = 0
        try:
            self._ensure_evidence_dir_exists()
        except Exception:
            return {"deleted_files": 0}

        files = [p for p in self._evidence_dir.iterdir() if p.is_file()]
        now = time.time()
        max_age = max(config.OPENCLAW_EVIDENCE_MAX_AGE_SECONDS, 0)
        max_files = max(config.OPENCLAW_EVIDENCE_MAX_FILES, 0)

        for file_path in files:
            try:
                if max_age > 0 and (now - file_path.stat().st_mtime) > max_age:
                    file_path.unlink(missing_ok=True)
                    deleted_files += 1
            except Exception:
                continue

        remaining = [p for p in self._evidence_dir.iterdir() if p.is_file()]
        if max_files > 0 and len(remaining) > max_files:
            remaining.sort(key=lambda p: p.stat().st_mtime)
            overflow = len(remaining) - max_files
            for file_path in remaining[:overflow]:
                try:
                    file_path.unlink(missing_ok=True)
                    deleted_files += 1
                except Exception:
                    continue
        return {"deleted_files": deleted_files}


def create_default_runtime_dispatcher() -> RuntimeDispatcher:
    if not config.OPENCLAW_RUNTIME_ENABLED:
        return NullRuntimeDispatcher()
    return PlaywrightRuntimeDispatcher()


def _build_evidence_ref_id(*, intent_id: str, workflow_execution_id: str) -> str:
    iid = _slug_fragment(intent_id, "intent")
    wid = _slug_fragment(workflow_execution_id, "wf")
    return f"ev-{iid}-{wid}-{uuid.uuid4().hex[:8]}"


def _slug_fragment(value: str, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    if not cleaned:
        return fallback
    return cleaned[:20]


def _validate_url(arguments: dict[str, Any]) -> str:
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    raw_url = arguments.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("arguments.url must be a non-empty string")
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("arguments.url must be an absolute http(s) URL")
    return raw_url.strip()


def _truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes]
    safe = truncated.decode("utf-8", errors="ignore")
    return safe, True


def _estimate_output_bytes(result: RuntimeResult) -> int:
    observation_bytes = len(json.dumps(result.observation, ensure_ascii=False).encode("utf-8"))
    evidence_bytes = 0
    for ref in result.evidence_refs:
        uri = ref.get("uri", "")
        if isinstance(uri, str):
            evidence_bytes += len(uri.encode("utf-8"))
    return observation_bytes + evidence_bytes
