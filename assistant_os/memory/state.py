"""
Gestión de estado persistente para Assistant OS.
Schema fijo con namespaces por agente + escritura atómica.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from ..config import STATE_FILE, MEMORY_DIR


def _now_iso() -> str:
    """Retorna timestamp actual en ISO8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    """Genera estado por defecto con schema correcto."""
    now = _now_iso()
    return {
        "session": {
            "id": str(uuid.uuid4()),
            "started_at": now,
            "last_active": now,
        },
        "agents": {
            # Legacy pipeline agents (CODE/DOC/JOBS/BIZ via prefix CLI)
            "code": {"last_task": None, "status": "idle", "iterations": 0},
            "doc": {"last_task": None, "status": "idle"},
            "jobs": {"last_task": None, "status": "idle", "results_count": 0},
            "biz": {"last_task": None, "status": "idle"},
            # Active pipeline domains (HTTP webhook)
            "work": {"last_action": None, "status": "idle"},
            "fin": {"last_action": None, "status": "idle"},
        },
    }


def load_state() -> dict[str, Any]:
    """
    Carga el estado desde state.json.
    Si no existe o está corrupto, crea uno por defecto.
    """
    if STATE_FILE.exists():
        try:
            content = STATE_FILE.read_text(encoding="utf-8")
            state = json.loads(content)
            # Validar estructura mínima
            if "session" in state and "agents" in state:
                return state
        except (json.JSONDecodeError, IOError, KeyError):
            pass
    
    # Crear estado por defecto
    state = _default_state()
    save_state(state)
    return state


def save_state(state: dict[str, Any]) -> None:
    """
    Persiste el estado con escritura atómica.
    Escribe a .tmp y luego renombra.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    
    tmp_file = STATE_FILE.with_suffix(".tmp")
    content = json.dumps(state, indent=2, ensure_ascii=False)
    
    # Escribir a archivo temporal
    tmp_file.write_text(content, encoding="utf-8")
    
    # Renombrar atómicamente (en Windows puede requerir eliminar primero)
    if os.name == "nt" and STATE_FILE.exists():
        STATE_FILE.unlink()
    tmp_file.rename(STATE_FILE)


def update_agent_state(agent: str, fields: dict[str, Any]) -> dict[str, Any]:
    """
    Actualiza solo el namespace de un agente específico.
    También actualiza session.last_active.
    
    Args:
        agent: nombre del agente ("code", "doc", "jobs", "biz")
        fields: campos a actualizar dentro del namespace del agente
    
    Returns:
        El estado completo actualizado
    """
    state = load_state()
    
    # Normalizar nombre del agente
    agent_key = agent.lower()
    
    # Asegurar que existe el namespace
    if agent_key not in state["agents"]:
        state["agents"][agent_key] = {}
    
    # Actualizar campos del agente
    state["agents"][agent_key].update(fields)
    
    # Actualizar last_active de la sesión
    state["session"]["last_active"] = _now_iso()
    
    save_state(state)
    return state


def get_agent_state(agent: str) -> dict[str, Any]:
    """Obtiene el estado de un agente específico."""
    state = load_state()
    agent_key = agent.lower()
    return state["agents"].get(agent_key, {})


def reset_state() -> dict[str, Any]:
    """Resetea el estado a valores por defecto."""
    state = _default_state()
    save_state(state)
    return state
