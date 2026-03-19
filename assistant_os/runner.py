"""
Runner seguro para ejecución de comandos.
Whitelist + workspace root + timeout + logs ndjson.
"""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from .config import (
    WORKSPACE_ROOT,
    LOG_FILE,
    TIMEOUT_SECONDS,
    is_command_allowed,
    MEMORY_DIR,
)


class RunResult(TypedDict):
    """Resultado de ejecución de comando."""
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    cmd: list[str]
    ts: str


def _now_iso() -> str:
    """Retorna timestamp actual en ISO8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _log_execution(result: RunResult) -> None:
    """Escribe log de ejecución en formato ndjson (append)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    log_entry = {
        "ts": result["ts"],
        "cmd": result["cmd"],
        "exit_code": result["exit_code"],
        "ok": result["ok"],
        "duration_ms": result["duration_ms"],
    }
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def run(cmd: list[str], timeout: int | None = None) -> RunResult:
    """
    Ejecuta un comando de forma segura.
    
    Args:
        cmd: Lista de argumentos del comando
        timeout: Timeout en segundos (usa TIMEOUT_SECONDS si no se especifica)
    
    Returns:
        RunResult con el resultado de la ejecución
    
    Raises:
        No lanza excepciones, devuelve error estructurado en RunResult
    """
    ts = _now_iso()
    timeout = timeout or TIMEOUT_SECONDS
    
    # Verificar whitelist
    if not is_command_allowed(cmd):
        result = RunResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=f"Command not allowed: {' '.join(cmd)}. "
                   f"Only whitelisted commands can be executed.",
            duration_ms=0,
            cmd=cmd,
            ts=ts,
        )
        _log_execution(result)
        return result
    
    # Ejecutar comando
    start_time = time.perf_counter()
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=WORKSPACE_ROOT,
            shell=False,  # NUNCA usar shell=True
        )
        
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        
        result = RunResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_ms=duration_ms,
            cmd=cmd,
            ts=ts,
        )
        
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        result = RunResult(
            ok=False,
            exit_code=-2,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            duration_ms=duration_ms,
            cmd=cmd,
            ts=ts,
        )
        
    except FileNotFoundError:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        result = RunResult(
            ok=False,
            exit_code=-3,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            duration_ms=duration_ms,
            cmd=cmd,
            ts=ts,
        )
        
    except Exception as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        result = RunResult(
            ok=False,
            exit_code=-4,
            stdout="",
            stderr=f"Execution error: {type(e).__name__}: {e}",
            duration_ms=duration_ms,
            cmd=cmd,
            ts=ts,
        )
    
    _log_execution(result)
    return result


def run_python_module(module: str, *args: str, timeout: int | None = None) -> RunResult:
    """Atajo para ejecutar módulos Python permitidos."""
    cmd = ["python", "-m", module] + list(args)
    return run(cmd, timeout=timeout)


def run_tests(verbose: bool = True, timeout: int | None = None) -> RunResult:
    """Ejecuta los tests generados del proyecto."""
    # Solo se permite ejecutar tests_generated con discover
    return run(["python", "-m", "unittest", "discover", "-v", "-s", "tests_generated"], timeout=timeout)
