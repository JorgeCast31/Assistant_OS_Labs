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
from typing import Any


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip diacritics, and remove leading/trailing/internal punctuation.

    Internal ?!¿¡ are collapsed to spaces so that multi-clause inputs like
    "Machine operator? Cuéntame más." match against clean pattern strings.
    """
    nfd = unicodedata.normalize("NFD", text.lower().strip())
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Strip leading/trailing inverted and standard punctuation
    stripped = ascii_text.strip("?!.,;:\xa1\xbf").strip()
    # Collapse sentence-internal ?!¿¡ into spaces
    cleaned = []
    for ch in stripped:
        if ch in "?!\xa1\xbf":
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    return " ".join("".join(cleaned).split())


# ---------------------------------------------------------------------------
# Conversational pattern sets — exact match after normalization
# ---------------------------------------------------------------------------

_SYSTEM_CHAT_CONVERSATIONAL: frozenset[str] = frozenset({
    # Greetings
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "hola que tal",
    "como estas",

    # Identity / what-are-you
    "que eres",
    "que eres tu",

    # Capabilities (general)
    "que puedes hacer",
    "que capacidades tienes",
    "que capacidades tienes ahora",
    "cuales son tus capacidades",
    "analiza tus capacidades",
    "que capacidades hay",

    # Agents
    "que agentes tienes",
    "cuantos agentes tienes",

    # System state / activity
    "estado del sistema",
    "esta activo",
    "que esta activo",
    "que hay activo",
    "que esta corriendo",
    "que hay corriendo",
    "que procesos hay",

    # Machine Operator
    "tienes machine operator",
    "hay machine operator",
    "machine operator",
    "machine operator cuentame mas",
    "el sistema tiene machine operator",
    "tienes mo",

    # System functionality
    "como funciona el sistema",
    "como funciona esto",
    "como funciona",

    # MSO usage guide
    "como uso el mso",
    "como uso machine operator",

    # Conversational
    "quiero conversar",
    "conversa conmigo",
    "conversemos",
    "platicamos",
    "hablemos",
    "cuentame",
    "cuentame mas",

    # Help
    "ayuda",
    "help",
})

_MSO_DIRECT_CONVERSATIONAL: frozenset[str] = frozenset({
    # Greetings
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",

    # Identity
    "quien eres",
    "quien eres tu",
    "que eres",
    "que eres tu",

    # Capabilities / delegation
    "que puedes hacer",
    "que puedes delegar",
    "que puedes orquestar",
    "que puedes coordinar",

    # Agents
    "que agentes estan disponibles",
    "cuales agentes estan disponibles",
    "que agentes hay",

    # Machine Operator
    "tienes machine operator",
    "hay machine operator",
    "machine operator",
    "esta activo",

    # Context / access
    "tienes acceso a las ultimas acciones del sistema",
    "tienes acceso a las acciones del sistema",
    "puedes leer esta conversacion",
    "puedes ver esta conversacion",

    # Help
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
    "corre ",
    "correr",
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
# Shared read-model helpers
# ---------------------------------------------------------------------------

def _machine_operator_summary() -> str:
    try:
        from .operability import build_system_capabilities_response
        caps = build_system_capabilities_response()
        mo_state = (caps.get("features") or {}).get("machine_operator", "unknown")
    except Exception:
        mo_state = "unknown"

    if mo_state == "unavailable":
        return (
            "Machine Operator está disponible en modo simulación. "
            "La capa MSO está activa y procesa decisiones localmente, "
            "pero la conexión con el gateway externo (OpenClaw) no está configurada. "
            "Toda ejecución pasa por política → plan → confirmación."
        )
    if mo_state == "available":
        return (
            "Machine Operator está activo. Evalúo solicitudes contra la política de gobernanza, "
            "genero planes de ejecución y requiero confirmación explícita antes de actuar. "
            "¿Tienes alguna solicitud ejecutiva?"
        )
    return (
        "Machine Operator es la capa de decisiones soberana del sistema. "
        "Actualmente en modo simulación — las decisiones se procesan localmente. "
        "Toda acción requiere política → plan → confirmación explícita."
    )


def _active_executions_summary() -> str:
    try:
        from .operability import build_mso_state_response
        state = build_mso_state_response()
        active = state.get("active_executions", 0)
        pending = state.get("pending_confirmations", 0)
        mode = state.get("operational_mode", "UNKNOWN")
        parts: list[str] = []
        if active:
            parts.append(f"{active} ejecución(es) activa(s).")
        if pending:
            parts.append(f"{pending} confirmación(es) pendiente(s).")
        if not parts:
            parts.append("No hay ejecuciones activas en este momento.")
        parts.append(f"Modo operacional: {mode}.")
        return " ".join(parts)
    except Exception:
        return "Estado de ejecuciones disponible en el panel de operabilidad."


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


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

_SYSTEM_CHAT_GREETING_SET = frozenset({
    "hola", "buenos dias", "buenas tardes", "buenas noches", "hola que tal", "como estas",
})

_SYSTEM_CHAT_MACHINE_OPERATOR_SET = frozenset({
    "tienes machine operator", "hay machine operator", "machine operator",
    "machine operator cuentame mas", "el sistema tiene machine operator", "tienes mo",
})

_SYSTEM_CHAT_CAPABILITY_SET = frozenset({
    "que puedes hacer", "que capacidades tienes", "que capacidades tienes ahora",
    "cuales son tus capacidades", "analiza tus capacidades", "que capacidades hay",
})

_SYSTEM_CHAT_ACTIVITY_SET = frozenset({
    "esta activo", "que esta activo", "que hay activo",
    "que esta corriendo", "que hay corriendo", "que procesos hay",
})

_SYSTEM_CHAT_CONVERSATION_SET = frozenset({
    "quiero conversar", "conversa conmigo", "conversemos", "platicamos",
    "hablemos", "cuentame", "cuentame mas",
})


def _system_chat_message(normalized: str) -> str:
    if normalized in _SYSTEM_CHAT_GREETING_SET:
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

    if normalized in _SYSTEM_CHAT_CAPABILITY_SET:
        return _capabilities_summary()

    if normalized in ("que agentes tienes", "cuantos agentes tienes"):
        return _agents_summary()

    if normalized == "estado del sistema":
        return _system_state_summary()

    if normalized in _SYSTEM_CHAT_MACHINE_OPERATOR_SET:
        return _machine_operator_summary()

    if normalized in ("como funciona el sistema", "como funciona esto", "como funciona"):
        return (
            "El sistema recibe solicitudes en lenguaje natural, las clasifica por dominio "
            "(WORK, CODE, HOST, FIN), evalúa la política de gobernanza, genera un plan "
            "y solicita confirmación antes de ejecutar. "
            "Ninguna acción ejecutiva ocurre sin autoridad explícita."
        )

    if normalized in _SYSTEM_CHAT_ACTIVITY_SET:
        return _active_executions_summary()

    if normalized in ("como uso el mso", "como uso machine operator"):
        return (
            "El MSO (Machine Operator) es la capa soberana de decisiones. "
            "Envíame una solicitud en lenguaje natural — la clasificaré, generaré un plan "
            "y solicitaré confirmación antes de ejecutar cualquier acción. "
            "Las acciones ejecutivas requieren autoridad explícita."
        )

    if normalized in _SYSTEM_CHAT_CONVERSATION_SET:
        return (
            "Con gusto. Estoy disponible para preguntas sobre el sistema, "
            "sus capacidades y agentes. Para acciones ejecutivas, envía tu solicitud "
            "y la procesaré a través del flujo de gobernanza."
        )

    return "Sistema operativo disponible. ¿En qué puedo ayudarte?"


# ---------------------------------------------------------------------------

_MSO_MACHINE_OPERATOR_SET = frozenset({
    "tienes machine operator", "hay machine operator", "machine operator", "esta activo",
})

_MSO_AGENTS_SET = frozenset({
    "que agentes estan disponibles", "cuales agentes estan disponibles", "que agentes hay",
})

_MSO_DELEGATION_SET = frozenset({
    "que puedes delegar", "que puedes orquestar", "que puedes coordinar",
})

_MSO_CONTEXT_SET = frozenset({
    "tienes acceso a las ultimas acciones del sistema",
    "tienes acceso a las acciones del sistema",
    "puedes leer esta conversacion",
    "puedes ver esta conversacion",
})


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

    if normalized in _MSO_MACHINE_OPERATOR_SET:
        return _machine_operator_summary()

    if normalized in _MSO_AGENTS_SET:
        return _agents_summary()

    if normalized in _MSO_DELEGATION_SET:
        return (
            "Como MSO puedo delegar a los agentes especializados del sistema: "
            "WORK (tareas y proyectos), CODE (código y scripts), "
            "HOST (operaciones del sistema) y FIN (consultas financieras). "
            "Cada delegación requiere política aprobada y confirmación explícita."
        )

    if normalized in _MSO_CONTEXT_SET:
        return (
            "Tengo acceso al estado operacional del sistema, eventos recientes, "
            "tareas activas y decisiones de gobernanza. "
            "No tengo acceso a conversaciones anteriores fuera de esta sesión. "
            "¿Qué información necesitas?"
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
