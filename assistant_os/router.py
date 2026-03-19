"""
Command Router - Clasifica comandos por prefijo y ejecuta el handler correspondiente.
Compatible con contratos Request/Response (Paso 3).
"""
import re
from typing import Any

from .contracts import (
    Request, Response,
    new_context_id, now_iso,
    make_error, make_ok,
)
from .memory.state import update_agent_state
from .agents.code_agent import CodeAgent
from .agents.doc_agent import DocAgent
from .agents.job_agent import JobAgent
from .agents.biz_agent import BizAgent

# Mapeo de prefijos a agentes
AGENT_MAP: dict[str, type] = {
    "code": CodeAgent,
    "doc": DocAgent,
    "jobs": JobAgent,
    "biz": BizAgent,
}

# Regex para detectar prefijo (case-insensitive, tolera espacios)
PREFIX_PATTERN = re.compile(r"^\s*(CODE|DOC|JOBS|BIZ)\s*:\s*(.*)$", re.IGNORECASE)


def parse_command_to_request(raw: str) -> Request:
    """
    Parsea un comando string a una Request estructurada.
    
    Args:
        raw: Comando en texto (ej: "CODE: crea módulo tensors")
    
    Returns:
        Request con agent, action, payload
    """
    raw = raw.strip()
    context_id = new_context_id()
    ts = now_iso()
    
    if not raw:
        return Request(
            context_id=context_id,
            agent="unknown",
            action="empty_command",
            payload={"raw": raw},
            ts=ts,
        )
    
    match = PREFIX_PATTERN.match(raw)
    
    if not match:
        return Request(
            context_id=context_id,
            agent="unknown",
            action="invalid_prefix",
            payload={"raw": raw},
            ts=ts,
        )
    
    prefix = match.group(1).lower()
    task_text = match.group(2).strip()
    
    return Request(
        context_id=context_id,
        agent=prefix,
        action="run_task",
        payload={"raw": raw, "task": task_text},
        ts=ts,
    )


def route_request(req: Request) -> Response:
    """
    Enruta una Request al agente correspondiente.
    
    Args:
        req: Request estructurada
    
    Returns:
        Response del agente
    """
    agent_name = req["agent"]
    context_id = req["context_id"]
    
    # Manejar agente desconocido
    if agent_name == "unknown":
        action = req["action"]
        if action == "empty_command":
            return make_error(
                agent="unknown",
                context_id=context_id,
                message="No se proporcionó ningún comando",
                err_type="EmptyCommand",
            )
        else:
            return make_error(
                agent="unknown",
                context_id=context_id,
                message="Prefijo no reconocido. Usa: CODE:, DOC:, JOBS:, BIZ:",
                err_type="InvalidPrefix",
            )
    
    # Obtener clase del agente
    agent_class = AGENT_MAP.get(agent_name)
    if not agent_class:
        return make_error(
            agent=agent_name,
            context_id=context_id,
            message=f"Agente '{agent_name}' no implementado",
            err_type="AgentNotFound",
        )
    
    # Ejecutar agente
    try:
        agent = agent_class()
        response = agent.run(req)
        
        # Actualizar estado del agente
        update_agent_state(agent_name, {
            "last_task": req["payload"].get("task", req["payload"].get("raw")),
            "status": response["status"],
        })
        
        return response
        
    except Exception as e:
        return make_error(
            agent=agent_name,
            context_id=context_id,
            message=f"Error ejecutando agente: {type(e).__name__}: {e}",
            err_type="AgentError",
        )


def route_command(command: str) -> dict[str, Any]:
    """
    Función de compatibilidad: procesa comando string y devuelve Response como dict.
    Mantiene compatibilidad con CLI existente.
    
    Args:
        command: Texto del comando
    
    Returns:
        Response como dict
    """
    req = parse_command_to_request(command)
    response = route_request(req)
    return dict(response)
