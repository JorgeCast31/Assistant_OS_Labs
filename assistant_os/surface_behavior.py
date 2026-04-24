"""Surface Behavior Layer — conversational short-circuit for surface-aware inputs.

Intercepts clearly non-executive inputs on specific UI surfaces (system_chat,
mso_direct) and returns informational responses WITHOUT invoking the orchestrator,
policy engine, or any execution path.

Core constraint:
  surface may influence conversational handling.
  surface is NEVER an authority verdict.
  Any actionable/executive input passes through unchanged.
"""
from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, remove diacritics, strip leading/trailing punctuation."""
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return ascii_text.strip("?!.,;:\xa1\xbf").strip()


# ---------------------------------------------------------------------------
# Conversational pattern sets — exact match after normalization
# ---------------------------------------------------------------------------

_SYSTEM_CHAT_CONVERSATIONAL: frozenset[str] = frozenset({
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "hola que tal",
    "como estas",
    "que eres",
    "que eres tu",
    "que puedes hacer",
    "quiero conversar",
    "conversa conmigo",
    "que agentes tienes",
    "cuantos agentes tienes",
    "estado del sistema",
    "como uso el mso",
    "como uso machine operator",
    "ayuda",
    "help",
})

_MSO_DIRECT_CONVERSATIONAL: frozenset[str] = frozenset({
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "quien eres",
    "quien eres tu",
    "que eres",
    "que eres tu",
    "que puedes hacer",
    "ayuda",
    "help",
})

# Executive prefixes — these MUST pass through the orchestrator unchanged.
_MSO_EXECUTIVE_PREFIXES: tuple[str, ...] = (
    "crea ",
    "ejecuta",
    "abre ",
    "modifica",
    "haz ",
    "borra ",
    "aplica",
    "lanza",
    "create ",
    "execute",
    "open ",
    "modify",
    "make ",
    "delete ",
    "apply",
    "launch",
    "run ",
    "start ",
    "stop ",
    "kill ",
    "deploy",
)


def _is_executive(normalized: str) -> bool:
    return any(normalized.startswith(p) for p in _MSO_EXECUTIVE_PREFIXES)


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _system_chat_message(normalized: str) -> str:
    if normalized in ("hola", "buenos dias", "buenas tardes", "buenas noches",
                      "hola que tal", "como estas"):
        return (
            "Hola. Soy el Asistente Operativo Soberano. Gestiono tareas, código, "
            "operaciones del sistema y consultas financieras. ¿En qué puedo ayudarte?"
        )

    if normalized in ("que eres", "que eres tu"):
        return (
            "Soy el Asistente Operativo Soberano — un sistema de ejecución gobernada. "
            "Proceso solicitudes ejecutivas a través de política, planificación y confirmación. "
            "Cuento con agentes especializados en trabajo (WORK), código (CODE), "
            "host (HOST) y finanzas (FIN)."
        )

    if normalized == "que puedes hacer":
        return _capabilities_summary()

    if normalized in ("que agentes tienes", "cuantos agentes tienes"):
        return _agents_summary()

    if normalized == "estado del sistema":
        return _system_state_summary()

    if normalized in ("como uso el mso", "como uso machine operator"):
        return (
            "El MSO (Machine Operator) es la capa soberana de decisiones. "
            "Envíame una solicitud en lenguaje natural — la clasificaré, generaré un plan "
            "y solicitaré confirmación antes de ejecutar cualquier acción. "
            "Las acciones ejecutivas requieren autoridad explícita."
        )

    if normalized in ("quiero conversar", "conversa conmigo"):
        return (
            "Con gusto. Estoy disponible para preguntas sobre el sistema, "
            "sus capacidades y agentes. Para acciones ejecutivas, envía tu solicitud "
            "y la procesaré a través del flujo de gobernanza."
        )

    return "Sistema operativo disponible. ¿En qué puedo ayudarte?"


def _capabilities_summary() -> str:
    try:
        from .operability import build_system_capabilities_response
        caps = build_system_capabilities_response()
        domains = caps.get("domains") or []
        features = caps.get("features") or {}
        capabilities = caps.get("capabilities") or []
        active = [c["id"] for c in capabilities if c.get("status") == "active"][:6]
        parts: list[str] = []
        if domains:
            parts.append(f"Dominios activos: {', '.join(domains)}.")
        if active:
            parts.append(f"Capacidades disponibles: {', '.join(active)}.")
        if features.get("machine_operator"):
            parts.append("Machine Operator habilitado.")
        if features.get("runner_enforced"):
            parts.append("Ejecución gobernada por runner.")
        return " ".join(parts) if parts else (
            "Capacidades del sistema: WORK, CODE, HOST, FIN. "
            "Todas las acciones ejecutivas requieren gobernanza."
        )
    except Exception:
        return (
            "Capacidades del sistema: WORK (tareas), CODE (código), "
            "HOST (sistema), FIN (finanzas). Todas requieren gobernanza para ejecutarse."
        )


def _agents_summary() -> str:
    try:
        from .operability import build_agents_registry_response
        result = build_agents_registry_response()
        agents = result.get("agents") or []
        if not agents:
            return "No hay agentes registrados actualmente."
        lines = [
            f"- {a['name']} ({a.get('domain', '?')}): {a.get('description') or 'sin descripción'}"
            for a in agents[:8]
        ]
        return f"Agentes disponibles ({len(agents)}):\n" + "\n".join(lines)
    except Exception:
        return "Agentes del sistema disponibles. Consulta el panel de sistema para detalles."


def _system_state_summary() -> str:
    try:
        from .operability import build_mso_state_response
        state = build_mso_state_response()
        mode = state.get("operational_mode", "UNKNOWN")
        agents_avail = state.get("agents_available", 0)
        pending = state.get("pending_confirmations", 0)
        active = state.get("active_executions", 0)
        parts = [f"Modo operacional: {mode}."]
        if agents_avail:
            parts.append(f"Agentes disponibles: {agents_avail}.")
        if pending:
            parts.append(f"Confirmaciones pendientes: {pending}.")
        if active:
            parts.append(f"Ejecuciones activas: {active}.")
        return " ".join(parts)
    except Exception:
        return "Estado del sistema disponible en el panel de operabilidad."


def _mso_conversational_message(normalized: str) -> str:
    if normalized in ("hola", "buenos dias", "buenas tardes", "buenas noches"):
        return (
            "Hola. Soy el MSO — la capa soberana de decisiones del sistema. "
            "Proceso solicitudes ejecutivas a través de política, plan y confirmación explícita. "
            "Las acciones de trabajo, código, host o finanzas deben ser aprobadas antes de ejecutarse. "
            "¿Tienes alguna solicitud?"
        )

    if normalized in ("quien eres", "quien eres tu", "que eres", "que eres tu"):
        return (
            "Soy el MSO (Machine Operator) — la capa de decisiones soberana del sistema. "
            "Evalúo cada solicitud contra la política de gobernanza, genero planes de ejecución "
            "y requiero confirmación explícita antes de ejecutar acciones. "
            "No ejecuto nada sin autoridad. ¿En qué puedo ayudarte?"
        )

    if normalized == "que puedes hacer":
        return (
            "Como MSO proceso: tareas de trabajo (WORK), operaciones de código (CODE), "
            "acciones del sistema (HOST) y consultas financieras (FIN). "
            "Toda acción ejecutiva requiere política → plan → confirmación. "
            "¿Qué solicitud tienes?"
        )

    return "MSO disponible. Las solicitudes ejecutivas pasan por gobernanza antes de ejecutarse."


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_surface_response(
    *,
    message: str,
    domain: str,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
) -> dict:
    return {
        "ok": True,
        "message": message,
        "trace_id": context_id,
        "domain": domain,
        "intent": "informational_response",
        "mode": "chat",
        "needs_confirmation": False,
        "missing_fields": [],
        "plan": [],
        "ui_actions": [],
        "session": {"context_id": context_id, "last_domain": domain},
        "audit": {
            "result_type": "surface_response",
            "domain": domain,
            "execution_mode": "",
            "mso_decided": False,
            "surface": surface,
        },
        "identity": identity.to_audit_dict(),
        "guard": guard_result.to_audit_dict(),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_surface_behavior_response(
    *,
    surface: str,
    text: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
) -> dict | None:
    """Return a surface-aware conversational response, or None to continue normal path.

    Returns None for:
    - empty/unknown surface
    - executive inputs on mso_direct (they must go through the orchestrator)
    - any input not in the conversational pattern set

    Never changes authority semantics. Never generates a plan.
    """
    if not surface or not text:
        return None

    normalized = _normalize(text)
    if not normalized:
        return None

    if surface == "system_chat":
        if normalized not in _SYSTEM_CHAT_CONVERSATIONAL:
            return None
        return _build_surface_response(
            message=_system_chat_message(normalized),
            domain="SYSTEM",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
        )

    if surface == "mso_direct":
        if _is_executive(normalized):
            return None
        if normalized not in _MSO_DIRECT_CONVERSATIONAL:
            return None
        return _build_surface_response(
            message=_mso_conversational_message(normalized),
            domain="MSO",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
        )

    return None
