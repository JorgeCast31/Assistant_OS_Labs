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

import re
import unicodedata
from dataclasses import dataclass, field as _dc_field
from typing import Any

from .cognition.context_resolver import (
    make_code_repo_context_request,
    maybe_create_fin_context_request,
)
from .cognition.router import RouterResult, route_text
from .contracts import now_iso


# ---------------------------------------------------------------------------
# SPRINT-ALPHA-05.5: MSO context — seat / mode / cognition tier
# ---------------------------------------------------------------------------

_VALID_MSO_SEATS: frozenset[str] = frozenset({
    "mso", "system_assistant", "machine_operator", "code", "work", "fin",
})
_VALID_MSO_MODES: frozenset[str] = frozenset({
    "conversational", "planning", "validation", "orchestration",
})
_VALID_MSO_TIERS: frozenset[str] = frozenset({"economic", "advanced"})


@dataclass(frozen=True)
class _MSOContext:
    agent_seat: str
    interaction_mode: str
    cognition_tier: str
    mode_source: str = "ui_selected"
    warnings: list = _dc_field(default_factory=list)


def _parse_mso_context(raw: dict | None) -> _MSOContext | None:
    """Return None when raw is None or not a dict (absent → backward-compat path).

    On invalid values fail closed to safe defaults and record warnings.
    Never raises.
    """
    if raw is None or not isinstance(raw, dict):
        return None
    warnings: list[str] = []
    seat = raw.get("agent_seat", "mso")
    if seat not in _VALID_MSO_SEATS:
        warnings.append(f"unknown agent_seat={seat!r}; defaulting to 'mso'")
        seat = "mso"
    mode = raw.get("interaction_mode", "conversational")
    if mode not in _VALID_MSO_MODES:
        warnings.append(f"unknown interaction_mode={mode!r}; defaulting to 'conversational'")
        mode = "conversational"
    tier = raw.get("cognition_tier", "economic")
    if tier not in _VALID_MSO_TIERS:
        warnings.append(f"unknown cognition_tier={tier!r}; defaulting to 'economic'")
        tier = "economic"
    return _MSOContext(
        agent_seat=seat,
        interaction_mode=mode,
        cognition_tier=tier,
        warnings=warnings,
    )


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

_ASSISTANT_CHAT_CONVERSATIONAL: frozenset[str] = frozenset({
    "hola",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "como estas",
    "hey",
})

_ASSISTANT_CHAT_STATUS: frozenset[str] = frozenset({
    "estado del sistema",
    "salud del sistema",
    "que esta activo",
})

_MSO_STATUS_QUERY_SET: frozenset[str] = frozenset({
    "estado del mso",
    "mso status",
    "cual es tu estado",
    "que modos tienes",
    "cuales son tus modos",
    "que modelo tienes sentado",
    "esta integrado police",
    "es runner fail-closed",
    "can mso execute directly",
    "show mso status",
    "muestra estado mso",
    "que seats tienes disponibles",
    "que seat tienes",
    "cual es el seat mas barato",
    "cual es el mas barato",
    "cual tiene mejor calidad precio",
    "cual conviene por calidad precio",
    "cual es el seat mas fuerte",
    "muestra estado del seat",
    "seat status",
    "que seats hay",
})

_MSO_SEAT_CHANGE_SET: frozenset[str] = frozenset({
    "cambia el seat del mso a claude",
    "cambia el seat del mso a anthropic",
    "cambia el seat del mso a llama",
    "cambia el seat del mso a openai",
    "cambia el seat del mso a gemma",
    "cambia seat a claude",
    "cambia seat a anthropic",
    "cambia seat a llama",
    "cambia seat a openai",
    "cambia seat a gemma",
    "change seat to claude",
    "change seat to anthropic",
    "change seat to llama",
    "change seat to openai",
    "change seat to gemma",
})

_GITHUB_URL_RE = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+", re.IGNORECASE)
_NUMERIC_AMOUNT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")

_CODE_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:analiza|analizar|revisa|revisar|audita|auditar)\b.*\b(?:repo|repositorio|github|codigo|code)\b", re.IGNORECASE),
    re.compile(r"\b(?:repo|repositorio|github|codigo|code)\b.*\b(?:analiza|analizar|revisa|revisar|audita|auditar)\b", re.IGNORECASE),
)

_FIN_EXPENSE_INCOMPLETE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:gaste|gasto|pague|compre)\b", re.IGNORECASE),
)

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
            "Machine Operator está configurado en modo simulación. "
            "La capa MSO procesa decisiones localmente, "
            "pero la conexión con el gateway externo (OpenClaw) no está configurada. "
            "Toda ejecución pasa por política → plan → confirmación."
        )
    if mo_state == "available":
        return (
            "Machine Operator está configurado. Sin verificación de reachability en este resumen. "
            "Evalúo solicitudes contra la política de gobernanza, genero planes de ejecución "
            "y requiero confirmación explícita antes de actuar. "
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
            parts.append(f"Dominios registrados: {', '.join(domains)}.")
        if active:
            parts.append(f"Capacidades registradas: {', '.join(active)}.")
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
        return f"Agentes registrados ({len(agents)}):\n" + "\n".join(lines)
    except Exception:
        return "Agentes del sistema registrados/configurados. Consulta el panel de sistema para detalles."


def _system_state_summary() -> str:
    try:
        from .operability import build_mso_state_response
        state = build_mso_state_response()
        mode = state.get("operational_mode", "UNKNOWN")
        agents_registered = state.get("agents_registered", state.get("agents_available", 0))
        pending = state.get("pending_confirmations", 0)
        active = state.get("active_executions", 0)
        parts = [f"Modo operacional: {mode}."]
        if agents_registered:
            parts.append(f"Agentes registrados/configurados: {agents_registered}.")
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

    return "Sistema operativo cargado. ¿En qué puedo ayudarte?"


# ---------------------------------------------------------------------------

def _assistant_chat_message(normalized: str) -> str:
    if normalized in _ASSISTANT_CHAT_CONVERSATIONAL:
        return "Hola. Estoy listo para conversar, revisar estado o ayudarte a encaminar una solicitud."
    if normalized in _ASSISTANT_CHAT_STATUS:
        return _system_state_summary()
    return "Necesito un poco mas de contexto para encaminar eso correctamente."


def _is_code_context_request(normalized: str) -> bool:
    return any(pattern.search(normalized) for pattern in _CODE_CONTEXT_PATTERNS)


def _has_code_context(normalized: str) -> bool:
    return bool(_GITHUB_URL_RE.search(normalized)) or bool(re.search(r"(?<!\w)(?:\.\/|\.\.\/|[a-z]:[\\/]|/)[^\s]+", normalized))


def _is_incomplete_fin_expense(normalized: str) -> bool:
    if not any(pattern.search(normalized) for pattern in _FIN_EXPENSE_INCOMPLETE_PATTERNS):
        return False
    return not bool(_NUMERIC_AMOUNT_RE.search(normalized))


def _is_fin_expense_request(normalized: str) -> bool:
    return any(pattern.search(normalized) for pattern in _FIN_EXPENSE_INCOMPLETE_PATTERNS)


def _is_ambiguous_assistant_chat(normalized: str) -> bool:
    if normalized in _ASSISTANT_CHAT_CONVERSATIONAL or normalized in _ASSISTANT_CHAT_STATUS:
        return False
    if _is_code_context_request(normalized) or _is_incomplete_fin_expense(normalized):
        return False
    if _is_fin_expense_request(normalized):
        return False
    if _is_executive(normalized):
        return False
    return len(normalized.split()) <= 5


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

    return "MSO registrado. Las solicitudes ejecutivas pasan por gobernanza antes de ejecutarse."


def _safe_build_mso_entity_status() -> dict:
    try:
        from .mso.entity_status import build_mso_entity_status
        return build_mso_entity_status()
    except Exception:
        return {
            "entity": "MSO",
            "status": "unknown",
            "authority_chain": {
                "police_gate": True,
                "runner_fail_closed": True,
                "authority_artifact_version": "2",
            },
            "surfaces": {
                "mso_direct": {"can_execute": False, "used_execution": False},
            },
            "interaction_modes": ["conversational", "planning", "validation", "orchestration", "status"],
            "model_seat": {"availability": "unknown"},
        }


def _safe_build_mso_seat_status() -> dict:
    try:
        from .mso.seat_status import build_mso_seat_status
        return build_mso_seat_status()
    except Exception:
        return {
            "active_seat": {"provider": None, "availability": "unknown", "can_execute": False},
            "available_seats": [],
            "selection": {"current_provider": None, "can_change_runtime": True, "change_method": "runtime_store"},
            "used_execution": False,
            "cognitive_only": True,
        }


def _mso_seat_change_message(normalized: str) -> str:
    """Return a deterministic response for seat-change requests."""
    # Detect which provider the user wants
    provider_map = {
        "claude": "anthropic", "anthropic": "anthropic",
        "llama": "llama", "openai": "openai", "gemma": "gemma",
    }
    requested = None
    for keyword, pname in provider_map.items():
        if keyword in normalized:
            requested = pname
            break

    if requested is None:
        return (
            "Para cambiar el seat cognitivo del MSO, especifica el proveedor:\n"
            "  cambia seat a anthropic | llama | openai | gemma\n\n"
            "El cambio es runtime-only (en memoria). "
            "Para persistir: configura MSO_SEAT_PROVIDER en el entorno."
        )

    try:
        from .mso.seat_status import set_runtime_seat_provider
        result = set_runtime_seat_provider(requested)
        if result.get("ok"):
            return (
                f"Seat cognitivo cambiado a: {requested}\n"
                f"Nota: cambio runtime-only. {result.get('note', '')}\n"
                "El seat NO ejecuta directamente. Cognitivo únicamente."
            )
        else:
            err = result.get("error", "Error desconocido")
            return (
                f"No se pudo cambiar el seat a {requested!r}.\n"
                f"Razón: {err}\n"
                "Para persistir: configura MSO_SEAT_PROVIDER en el entorno."
            )
    except Exception as exc:
        return (
            f"No se pudo cambiar el seat: {exc}\n"
            "Configura MSO_SEAT_PROVIDER en el entorno para seleccionar proveedor."
        )


def _mso_entity_status_message(status: dict) -> str:
    chain = status.get("authority_chain", {})
    seat = status.get("model_seat", {})
    modes = status.get("interaction_modes", [])
    surfaces = status.get("surfaces", {})
    mso_direct = surfaces.get("mso_direct", {})
    next_actions = status.get("next_safe_actions", [])

    provider = seat.get("provider") or "none"
    model = seat.get("model") or "not configured"
    availability = seat.get("availability", "unknown")
    police = "active" if chain.get("police_gate") else "not active"
    runner = "fail-closed" if chain.get("runner_fail_closed") else "not enforced"
    artifact_v = chain.get("authority_artifact_version", "unknown")
    mso_direct_exec = "no" if not mso_direct.get("can_execute") else "yes"
    modes_str = ", ".join(modes) if modes else "unknown"
    next_str = "\n".join(f"  - {a}" for a in next_actions) if next_actions else "  - None"

    return (
        f"MSO Entity Status\n"
        f"-----------------\n"
        f"I am the MSO runtime boundary. I own the orchestrator.\n\n"
        f"Runtime:\n"
        f"  Kernel: assistant_os.mso.kernel.handle_sovereign_request\n"
        f"  Orchestrator owned: yes\n\n"
        f"Authority chain:\n"
        f"  Police gate: {police}\n"
        f"  Runner: {runner}\n"
        f"  AuthorityArtifact version: {artifact_v}\n\n"
        f"Surfaces:\n"
        f"  assistant_chat: can execute (through Police → Runner)\n"
        f"  mso_direct: cannot execute directly ({mso_direct_exec})\n"
        f"  code_api: external_local, not MSO-governed\n\n"
        f"Interaction modes: {modes_str}\n\n"
        f"Cognitive seat:\n"
        f"  Provider: {provider}\n"
        f"  Model: {model}\n"
        f"  Availability: {availability}\n\n"
        f"Next safe actions:\n{next_str}"
    )


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
    result_type: str = "surface_response",
    intent: str = "informational_response",
    missing_fields: list[str] | None = None,
    context_request: dict | None = None,
    response_source: str | None = None,
    execution_status: str | None = None,
    provider_used: str | None = None,
    model_used: str | None = None,
    cognitive_generation: bool = False,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    narrative_context: dict | None = None,
    cognitive_trace: dict | None = None,
    latency_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> dict:
    session = {"context_id": context_id, "last_domain": domain}
    audit = {
        "result_type": result_type,
        "domain": domain,
        "execution_mode": "",
        "mso_decided": False,
        "surface": surface,
    }
    if context_request is not None:
        session["context_request"] = dict(context_request)
        audit["context_request"] = dict(context_request)

    resp = {
        "ok": True,
        "message": message,
        "result_type": result_type,
        "trace_id": context_id,
        "domain": domain,
        "intent": intent,
        "mode": "chat",
        "needs_confirmation": False,
        "missing_fields": missing_fields or [],
        "plan": [],
        "ui_actions": [],
        "session": session,
        "audit": audit,
        "identity": identity.to_audit_dict(),
        "guard": guard_result.to_audit_dict(),
        "execution_allowed": False,
        "can_execute_now": False,
    }

    if response_source:
        resp["response_source"] = response_source
        resp["execution_status"] = execution_status
        resp["provider_used"] = provider_used
        resp["model_used"] = model_used
        resp["cognitive_generation"] = cognitive_generation
        resp["fallback_used"] = fallback_used
        resp["fallback_reason"] = fallback_reason
        resp["latency_ms"] = latency_ms
        resp["tokens_in"] = tokens_in
        resp["tokens_out"] = tokens_out

        if not cognitive_trace:
            resp["cognitive_trace"] = {
                "response_source": response_source,
                "execution_status": execution_status,
                "provider_used": provider_used,
                "model_used": model_used,
                "cognitive_generation": cognitive_generation,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "latency_ms": latency_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "execution_allowed": False,
                "can_execute_now": False,
            }
        else:
            resp["cognitive_trace"] = cognitive_trace

    if narrative_context:
        resp["narrative_context"] = narrative_context

    return resp


def _build_plan_request_provider_context() -> dict:
    """
    Return cognitive-only provider metadata for plan_request responses.

    Never makes network calls. Never returns execution authority.
    Fail-closed: if provider lookup raises, returns a safe unavailable context.
    """
    try:
        from .mso.seat_model_provider_registry import get_seated_provider, describe_seated_provider
        provider = get_seated_provider()
        if provider is not None:
            seated_dict = provider.to_dict()
        else:
            seated_dict = None
        return {
            "seated_provider": seated_dict,
            "provider_description": describe_seated_provider(),
            "cognitive_only": True,
            "used_execution": False,
            "non_executing": True,
        }
    except Exception:
        return {
            "seated_provider": None,
            "provider_description": "No cognitive provider is currently seated/configured.",
            "cognitive_only": True,
            "used_execution": False,
            "non_executing": True,
        }


def _build_plan_request_authority_data(user_intent: str) -> dict:
    """
    Build a non-executing proposal + authority preparation + confirmable action
    + queue entry for plan_request responses.

    Chain: make_orchestration_proposal → prepare_authority_from_proposal →
           build_confirmable_from_preparation → enqueue_confirmable_prepared_action.

    Side effect: enqueues the confirmable action in the process-local review queue.
    No network calls, no token issuance, no Police calls, no execution.
    Fail-closed: any exception returns safe dict with None values.

    Returns
    -------
    dict with keys:
        proposal_summary        — serialized MSOExecutionProposal (or None)
        authority_preparation   — serialized AuthorityPreparationRequest (or None)
        confirmable_action      — serialized ConfirmablePreparedAction (or None)
        queued_prepared_action  — serialized queue entry (or None)
        execution_allowed       — always False
        cognitive_only          — always True
    """
    try:
        from .mso.seat_model_provider_registry import make_orchestration_proposal
        from .mso.authority_preparation import prepare_authority_from_proposal
        from .mso.confirmable_prepared_action import build_confirmable_from_preparation
        from .mso.prepared_action_queue import enqueue_confirmable_prepared_action

        proposal = make_orchestration_proposal(
            user_intent=user_intent,
            domain="ASSISTANT",
            requested_action="PLAN_REVIEW",
            capability_name="plan_review",
            capability_scope=("plan_review",),
        )
        preparation = prepare_authority_from_proposal(proposal)
        confirmable = build_confirmable_from_preparation(
            preparation,
            plan_steps=proposal.plan_steps,
            risk_level=proposal.risk_level,
        )
        queue_entry = enqueue_confirmable_prepared_action(confirmable)
        return {
            "proposal_summary": proposal.to_dict(),
            "authority_preparation": preparation.to_dict(),
            "confirmable_action": confirmable.to_dict(),
            "queued_prepared_action": queue_entry.to_dict(),
            "execution_allowed": False,
            "cognitive_only": True,
        }
    except Exception:
        return {
            "proposal_summary": None,
            "authority_preparation": None,
            "confirmable_action": None,
            "queued_prepared_action": None,
            "execution_allowed": False,
            "cognitive_only": True,
        }


def _build_review_queue_status_data() -> tuple[str, list[dict]]:
    """
    Read the manual review queue and build a narrative message + item list.

    Read-only. Never executes, approves, issues tokens, calls Police, or
    creates AuthorizedPlan. Fail-closed: any exception returns an empty-queue
    safe response.

    Returns
    -------
    tuple[str, list[dict]]
        (message, pending_review_items)
    """
    try:
        from .mso.prepared_action_queue import list_pending_confirmable_action_dicts
        items = list_pending_confirmable_action_dicts()
    except Exception:
        items = []

    count = len(items)
    if count == 0:
        message = (
            "No hay acciones preparadas esperando revision manual en este momento. "
            "Para agregar una accion a la cola de revision, crea una solicitud de plan "
            "con una frase como 'Prepara un plan. No ejecutar.' "
            "Esto es revision manual, no ejecucion."
        )
    else:
        lines: list[str] = []
        for item in items:
            provider_note = ""
            if item.get("provider_name") or item.get("model_name"):
                provider_note = (
                    f" Proveedor: {item.get('provider_name') or 'N/A'}"
                    f"/{item.get('model_name') or 'N/A'}."
                )
            lines.append(
                f"- [{item['queue_entry_id']}] "
                f"Dominio: {item['domain']}, "
                f"Accion: {item['requested_action']}, "
                f"Capacidad: {item['capability_name']}, "
                f"Estado confirmacion: {item['human_confirmation_status']}, "
                f"execution_allowed={item['execution_allowed']}, "
                f"can_execute_now={item['can_execute_now']}."
                f"{provider_note}"
            )
        items_str = "\n".join(lines)
        message = (
            f"Acciones preparadas esperando revision manual ({count}):\n"
            f"{items_str}\n"
            "Esto es revision manual, no ejecucion. "
            "La confirmacion humana y la cadena de autoridad siguen pendientes."
        )

    return message, items


def _plan_request_message(provider_context: dict, authority_data: dict | None = None) -> str:
    """Build the plan_request message including seated provider info and pending authority."""
    description = provider_context.get("provider_description") or ""
    seated = provider_context.get("seated_provider")

    if seated and seated.get("is_available"):
        provider_note = (
            f"Proveedor cognitivo en el seat: {seated['provider_name']} "
            f"({seated['model_name']}) — modo plan-only, sin ejecucion."
        )
    elif description:
        provider_note = description
    else:
        provider_note = "No hay proveedor cognitivo configurado en el seat."

    pending_note = ""
    if authority_data:
        prep = authority_data.get("authority_preparation") or {}
        pending_steps: list[str] = prep.get("pending_authority_steps") or [
            "PolicyDecision", "CapabilityToken", "OperationBinding",
            "AuthorizedPlan", "PoliceGate",
        ]
        pending_note = (
            f" Autoridad pendiente: {' → '.join(pending_steps)}."
        )

    return (
        f"{provider_note} "
        "Solicitud de plan recibida. "
        "ESTO NO ES EJECUCION. "
        "Accion agregada a revision manual. "
        "El sistema puede describir los pasos de un plan para esta operacion, "
        "pero no ejecutara ninguna accion."
        f"{pending_note} "
        "Confirmacion humana explicita requerida antes de cualquier ejecucion. "
        "Describe la operacion que deseas planificar."
    )


def _assistant_chat_router_response(
    *,
    router_result: RouterResult,
    normalized: str,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
) -> dict | None:
    intent_type = router_result.get("intent_type", "unknown_ambiguous")

    if intent_type == "executable_intent" and router_result.get("should_pass_to_kernel") is True:
        return None

    if intent_type == "conversational":
        return _build_surface_response(
            message=_assistant_chat_message(normalized),
            domain="ASSISTANT",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="surface_response",
            intent="conversational_response",
        )

    if intent_type == "capability_summary":
        return _build_surface_response(
            message=_capabilities_summary(),
            domain="ASSISTANT",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="surface_response",
            intent="capability_summary",
        )

    if intent_type == "read_only_status":
        return _build_surface_response(
            message=_system_state_summary(),
            domain="SYSTEM",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="status_response",
            intent="status_response",
        )

    if intent_type == "plan_request":
        provider_context = _build_plan_request_provider_context()
        authority_data = _build_plan_request_authority_data(normalized)
        response = _build_surface_response(
            message=_plan_request_message(provider_context, authority_data),
            domain="ASSISTANT",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="surface_response",
            intent="plan_request",
        )
        response["provider_context"] = provider_context
        response["proposal_summary"] = authority_data.get("proposal_summary")
        response["authority_preparation"] = authority_data.get("authority_preparation")
        response["confirmable_action"] = authority_data.get("confirmable_action")
        response["queued_prepared_action"] = authority_data.get("queued_prepared_action")
        _ac_queued = authority_data.get("queued_prepared_action") or {}
        response["response_source"] = "assistant_chat_plan_request_prepared"
        response["execution_status"] = "not_executed"
        response["used_execution"] = False
        response["operation_trace"] = {
            "plan_request_prepared": True,
            "prepared_action_id": _ac_queued.get("queue_entry_id"),
            "confirmation_required": True,
            "visible_in_mission_control": True,
            "source_surface": surface,
            "execution_allowed": False,
            "can_execute_now": False,
            "used_execution": False,
        }
        return response

    if intent_type == "review_queue_status":
        msg, pending_items = _build_review_queue_status_data()
        response = _build_surface_response(
            message=msg,
            domain="ASSISTANT",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="surface_response",
            intent="review_queue_status",
        )
        response["pending_review_items"] = pending_items
        response["count"] = len(pending_items)
        response["execution_allowed"] = False
        response["can_execute_now"] = False
        return response

    if intent_type == "needs_context":
        return _build_surface_response(
            message=_assistant_chat_needs_context_message(router_result),
            domain=router_result.get("domain") or "UNKNOWN",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="clarification",
            intent="needs_context",
            missing_fields=router_result.get("missing_fields") or ["intent"],
        )

    # MSO Narrative Runtime — non-executing cognitive fallback for operational queries.
    # Intercepts unknown_ambiguous when normalized text matches safe MSO/operational patterns.
    try:
        from .mso.narrative_runtime import is_mso_narrative_intent, build_narrative_context_message
        if is_mso_narrative_intent(normalized):
            _msg, _ctx = build_narrative_context_message()
            _resp = _build_surface_response(
                message=_msg,
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="surface_response",
                intent="mso_narrative_status",
            )
            _resp["narrative_context"] = _ctx
            return _resp
    except Exception:
        pass

    return _build_surface_response(
        message=_assistant_chat_unknown_message(router_result),
        domain="UNKNOWN",
        surface=surface,
        context_id=context_id,
        identity=identity,
        guard_result=guard_result,
        result_type="clarification",
        intent="needs_context",
        missing_fields=["intent"],
    )


def _assistant_chat_router_fail_closed_response(
    *,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
) -> dict:
    return _build_surface_response(
        message="Necesito un poco mas de contexto para encaminar eso correctamente.",
        domain="UNKNOWN",
        surface=surface,
        context_id=context_id,
        identity=identity,
        guard_result=guard_result,
        result_type="clarification",
        intent="needs_context",
        missing_fields=["intent"],
    )


def _assistant_chat_needs_context_message(router_result: RouterResult) -> str:
    domain = router_result.get("domain")
    missing = set(router_result.get("missing_fields") or [])
    if domain == "CODE" and "repo_url" in missing:
        return "Necesito el URL del repositorio o una ruta de codigo para revisarlo."
    if domain == "FIN" and "amount" in missing:
        return "Necesito el monto para registrar ese gasto."
    if domain == "WORK" and "task_title" in missing:
        return "Necesito el titulo de la tarea para crearla."
    return "Necesito un poco mas de contexto para encaminar eso correctamente."


def _assistant_chat_unknown_message(router_result: RouterResult) -> str:
    flags = set(router_result.get("safety_flags") or [])
    if flags.intersection({"social_engineering", "prompt_injection"}):
        return "No puedo encaminar solicitudes que intentan saltarse reglas o instrucciones del sistema."
    return "Necesito un poco mas de contexto para encaminar eso correctamente."


# RC-2: English status phrases canonicalized to the Spanish form the router recognizes
_EN_STATUS_RE = re.compile(
    r"(?:report|what\s+is|current|sovereign|runtime)\b.{0,50}\bstatus\b"
    r"|\bsystem\s+status\b"
    r"|\bruntime\s+status\b"
)


def _assistant_chat_router_text(text: str, normalized: str) -> str:
    if re.search(r"\b(?:como esta|estado|salud)\b.*\bsistema\b", normalized):
        return "como esta el sistema"
    if _EN_STATUS_RE.search(normalized):
        return "como esta el sistema"
    return text


def _build_routing_context(router_result: RouterResult, context_id: str) -> dict | None:
    if router_result.get("intent_type") != "executable_intent":
        return None
    if router_result.get("should_pass_to_kernel") is not True:
        return None

    action = str(router_result.get("action") or "")
    action_upper = action.upper()
    if action_upper == "COMMAND" or action_upper.endswith("_COMMAND"):
        return None

    return {
        "source": "cognitive_router_v0",
        "authoritative": False,
        "intent_type": "executable_intent",
        "domain": router_result.get("domain") or "UNKNOWN",
        "action": action,
        "entities": dict(router_result.get("entities") or {}),
        "missing_fields": list(router_result.get("missing_fields") or []),
        "confidence": router_result.get("confidence", 0.0),
        "safety_flags": list(router_result.get("safety_flags") or []),
        "routing_reason": router_result.get("routing_reason") or "",
        "router_version": router_result.get("router_version") or "v0_deterministic",
        "context_id": context_id,
        "created_at": now_iso(),
    }


def get_assistant_chat_routing_context(
    *,
    surface: str,
    text: str,
    context_id: str,
) -> dict | None:
    """Return a non-authoritative routing context for assistant_chat pass-through.

    This helper is request-local and stateless. It never returns execution
    authority and never creates plans, tasks, confirmations, or side effects.
    """
    if surface != "assistant_chat" or not text:
        return None

    normalized = _normalize(text)
    if not normalized:
        return None

    if normalized in _ASSISTANT_CHAT_CONVERSATIONAL or normalized in _ASSISTANT_CHAT_STATUS:
        return None
    if _is_code_context_request(normalized) and not _has_code_context(normalized):
        return None
    if _is_incomplete_fin_expense(normalized):
        return None

    try:
        router_result = route_text(_assistant_chat_router_text(text, normalized))
    except Exception:
        return None

    return _build_routing_context(router_result, context_id)


# ---------------------------------------------------------------------------
# MSO cognitive generation helper
# ---------------------------------------------------------------------------

def _call_mso_cognitive(grounding_context: dict, text: str, history: list | None = None) -> dict:
    """Thin wrapper around mso_chat_provider.call_mso_chat_provider.

    Kept as a named module-level function so tests can patch it cleanly
    without importing from mso_chat_provider directly.
    """
    from .mso.mso_chat_provider import call_mso_chat_provider
    return call_mso_chat_provider(grounding_context=grounding_context, user_text=text, history=history)


def _get_vault_context(query: str, allowed_packs: list[str] | None = None) -> dict:
    """Thin wrapper around vault_context.build_vault_context for clean test patching."""
    from .mso.vault_context import build_vault_context
    return build_vault_context(query=query, allowed_packs=allowed_packs)


def build_mso_grounding_context() -> dict:
    """Module-level wrapper so tests can patch assistant_os.surface_behavior.build_mso_grounding_context."""
    from .mso.narrative_runtime import build_mso_grounding_context as _build
    return _build()


def build_narrative_context_message() -> tuple[str, dict]:
    """Module-level wrapper so tests can patch assistant_os.surface_behavior.build_narrative_context_message."""
    from .mso.narrative_runtime import build_narrative_context_message as _build
    return _build()


def _get_session_history(session_id: str | None, limit_turns: int = 5) -> dict:
    """Module-level wrapper so tests can patch assistant_os.surface_behavior._get_session_history."""
    from .mso.session_history import build_mso_session_history
    return build_mso_session_history(session_id=session_id, limit_turns=limit_turns)


# ---------------------------------------------------------------------------
# SPRINT-ALPHA-05.5: perception context builder (used by all mso_direct modes)
# ---------------------------------------------------------------------------

def _build_mso_perception_context(text: str, session_id: str | None) -> dict:
    """Build grounding + vault + session history for any mso_direct mode handler.

    Perception invariant: all modes keep MSO informed — mode changes the
    behavioral pipeline, not the observation context.

    Never raises. Individual failures are recorded in perception_warnings and
    surfaced honestly in the response, not silently swallowed.
    """
    perception_warnings: list[str] = []
    grounding: dict = {}
    vault_ctx: dict = {
        "enabled": False, "chunks": [], "vault_chunks_used": 0,
        "warnings": [], "packs_consulted": [],
    }
    session_hist: dict = {
        "available": False, "turns": [], "turns_used": 0,
        "source": "unavailable", "warnings": [],
    }
    try:
        grounding = build_mso_grounding_context()
    except Exception as _e:
        perception_warnings.append(f"grounding_failed: {_e}")
    try:
        vault_ctx = _get_vault_context(query=text)
    except Exception as _e:
        perception_warnings.append(f"vault_failed: {_e}")
    try:
        session_hist = _get_session_history(session_id)
    except Exception as _e:
        perception_warnings.append(f"session_history_failed: {_e}")
    return {
        "grounding": grounding,
        "vault_context": vault_ctx,
        "session_history": session_hist,
        "perception_context": {
            "grounding_available": bool(grounding),
            "vault_available": vault_ctx.get("enabled", False),
            "vault_chunks_used": vault_ctx.get("vault_chunks_used", 0),
            "vault_warnings": vault_ctx.get("warnings", []),
            "session_history_available": session_hist.get("available", False),
            "session_turns_used": session_hist.get("turns_used", 0),
            "session_warnings": session_hist.get("warnings", []),
            "perception_warnings": perception_warnings,
        },
    }


# ---------------------------------------------------------------------------
# SPRINT-ALPHA-05.5: mso_direct mode handlers
# ---------------------------------------------------------------------------

def _handle_mso_mode_conversational(
    *,
    text: str,
    mso_ctx: _MSOContext,
    perception: dict,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
    session_id: str | None = None,
) -> dict | None:
    """Mode: conversational — skip plan_request text check, go straight to cognitive path.

    Only agent_seat='mso' receives full cognitive generation in this sprint.
    Other seats degrade honestly through the MSO-controlled narrative path.
    """
    import time as _time
    grounding = perception["grounding"]
    vault_ctx = perception["vault_context"]
    session_hist = perception["session_history"]
    perception_context = perception["perception_context"]

    grounding_with_vault = {**grounding, "vault_context": vault_ctx, "session_history": session_hist}

    _start = _time.perf_counter()
    _latency_ms: int | None = None
    _provider_err: str | None = None
    try:
        _hist_turns = (
            session_hist["turns"]
            if session_hist.get("available") and session_hist.get("turns")
            else None
        )
        if _hist_turns:
            provider_resp = _call_mso_cognitive(grounding_with_vault, text, history=_hist_turns)
        else:
            provider_resp = _call_mso_cognitive(grounding_with_vault, text)
        _latency_ms = int((_time.perf_counter() - _start) * 1000)
        if provider_resp.get("status") == "ok" and provider_resp.get("text", "").strip():
            provider_metadata = provider_resp.get("metadata") or {}
            cognitive_trace = {
                "response_source": "llm_economic",
                "execution_status": "real",
                "provider_used": provider_resp.get("provider_name", ""),
                "model_used": provider_resp.get("model_name", ""),
                "cognitive_generation": True,
                "fallback_used": False,
                "fallback_reason": None,
                "latency_ms": _latency_ms,
                "tokens_in": provider_metadata.get("tokens_in"),
                "tokens_out": provider_metadata.get("tokens_out"),
                "execution_allowed": False,
                "can_execute_now": False,
                "vault_enabled": vault_ctx.get("enabled", False),
                "vault_chunks_used": vault_ctx.get("vault_chunks_used", 0),
                "vault_sources": vault_ctx.get("vault_sources", []),
                "history_available": session_hist.get("available", False),
                "history_turns_used": session_hist.get("turns_used", 0),
                "synthesis_mode": "economic",
                "interaction_mode": mso_ctx.interaction_mode,
                "agent_seat": mso_ctx.agent_seat,
                "cognition_tier": mso_ctx.cognition_tier,
                "mode_source": mso_ctx.mode_source,
                "mso_context_warnings": list(mso_ctx.warnings) or None,
            }
            resp = _build_surface_response(
                message=provider_resp["text"].strip(),
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="surface_response",
                intent="mso_cognitive_response",
                response_source="llm_economic",
                execution_status="real",
                provider_used=provider_resp.get("provider_name", ""),
                model_used=provider_resp.get("model_name", ""),
                cognitive_generation=True,
                fallback_used=False,
                narrative_context={**grounding_with_vault, "execution_allowed": False, "can_execute_now": False},
                latency_ms=_latency_ms,
                tokens_in=provider_metadata.get("tokens_in"),
                tokens_out=provider_metadata.get("tokens_out"),
                cognitive_trace=cognitive_trace,
            )
            resp["perception_context"] = perception_context
            try:
                from .mso.cognitive_usage_ledger import record_provider_call
                record_provider_call(
                    trace_id=context_id,
                    source_component="surface_behavior._handle_mso_mode_conversational",
                    surface=surface,
                    domain="MSO",
                    session_id=session_id,
                    agent_seat=mso_ctx.agent_seat,
                    effective_agent_seat="mso",
                    interaction_mode=mso_ctx.interaction_mode,
                    cognition_tier=mso_ctx.cognition_tier,
                    effective_cognition_tier=mso_ctx.cognition_tier,
                    provider_used=provider_resp.get("provider_name"),
                    model_used=provider_resp.get("model_name"),
                    tokens_in=provider_metadata.get("tokens_in"),
                    tokens_out=provider_metadata.get("tokens_out"),
                    latency_ms=_latency_ms,
                    action="mso_cognitive_response",
                    response_source="llm_economic",
                )
            except Exception:
                pass
            return resp
        else:
            _provider_err = provider_resp.get("error") or provider_resp.get("reason") or "unusable provider response"
    except Exception as _e:
        _latency_ms = int((_time.perf_counter() - _start) * 1000)
        _provider_err = str(_e)

    # Fallback to narrative
    try:
        _msg, _ctx = build_narrative_context_message()
        _fallback_source = (
            "provider_unavailable"
            if "key not configured" in str(_provider_err).lower()
            else "deterministic_fallback"
        )
        resp = _build_surface_response(
            message=_msg,
            domain="MSO",
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
            result_type="surface_response",
            intent="mso_narrative_status",
            response_source=_fallback_source,
            execution_status="unavailable",
            fallback_used=True,
            fallback_reason=_provider_err,
            narrative_context=_ctx,
            latency_ms=_latency_ms,
        )
        resp["perception_context"] = perception_context
        try:
            from .mso.cognitive_usage_ledger import record_provider_fallback
            record_provider_fallback(
                trace_id=context_id,
                source_component="surface_behavior._handle_mso_mode_conversational",
                surface=surface,
                domain="MSO",
                session_id=session_id,
                agent_seat=mso_ctx.agent_seat,
                effective_agent_seat="mso",
                interaction_mode=mso_ctx.interaction_mode,
                cognition_tier=mso_ctx.cognition_tier,
                effective_cognition_tier=mso_ctx.cognition_tier,
                response_source=_fallback_source,
                fallback_reason=_provider_err,
                latency_ms=_latency_ms,
                action="mso_narrative_status",
            )
        except Exception:
            pass
        return resp
    except Exception:
        return None


def _handle_mso_mode_planning(
    *,
    text: str,
    normalized: str,
    mso_ctx: _MSOContext,
    perception: dict,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
    session_id: str | None = None,
) -> dict:
    """Mode: planning — create governed plan entry regardless of text pattern.

    Uses the same authority chain as the existing text-driven Tier 3 path:
    make_orchestration_proposal → prepare_authority_from_proposal →
    build_confirmable_from_preparation → enqueue_confirmable_prepared_action.

    No token issuance. No PoliceGate. No runner. execution_allowed=False always.
    Only agent_seat='mso' triggers full plan preparation. Other seats degrade
    to the same path but are noted in operation_trace.
    """
    perception_context = perception["perception_context"]
    _pr_provider_ctx = _build_plan_request_provider_context()
    _pr_auth_data = _build_plan_request_authority_data(normalized)
    _pr_queued = _pr_auth_data.get("queued_prepared_action") or {}
    _pr_queued_id = _pr_queued.get("queue_entry_id")
    _pr_visible = bool(_pr_queued_id)
    resp = _build_surface_response(
        message=_plan_request_message(_pr_provider_ctx, _pr_auth_data),
        domain="ASSISTANT",
        surface=surface,
        context_id=context_id,
        identity=identity,
        guard_result=guard_result,
        result_type="surface_response",
        intent="plan_request",
    )
    resp["provider_context"] = _pr_provider_ctx
    resp["proposal_summary"] = _pr_auth_data.get("proposal_summary")
    resp["authority_preparation"] = _pr_auth_data.get("authority_preparation")
    resp["confirmable_action"] = _pr_auth_data.get("confirmable_action")
    resp["queued_prepared_action"] = _pr_queued
    resp["response_source"] = "mso_mode_planning_prepared"
    resp["execution_status"] = "not_executed"
    resp["used_execution"] = False
    resp["operation_trace"] = {
        "plan_request_prepared": _pr_visible,
        "prepared_action_id": _pr_queued_id,
        "confirmation_required": True,
        "visible_in_mission_control": _pr_visible,
        "source_surface": "mso_direct",
        "interaction_mode": "planning",
        "mode_source": mso_ctx.mode_source,
        "agent_seat": mso_ctx.agent_seat,
        "cognition_tier": mso_ctx.cognition_tier,
        "mso_context_warnings": list(mso_ctx.warnings) or None,
        "execution_allowed": False,
        "can_execute_now": False,
        "used_execution": False,
    }
    resp["perception_context"] = perception_context
    try:
        from .mso.cognitive_usage_ledger import record_mode_interaction
        record_mode_interaction(
            trace_id=context_id,
            source_component="surface_behavior._handle_mso_mode_planning",
            surface=surface,
            domain="MSO",
            session_id=session_id,
            agent_seat=mso_ctx.agent_seat,
            effective_agent_seat="mso",
            interaction_mode=mso_ctx.interaction_mode,
            cognition_tier=mso_ctx.cognition_tier,
            effective_cognition_tier=mso_ctx.cognition_tier,
            response_source="mso_mode_planning_prepared",
            action="plan_request",
            prepared_action_id=_pr_queued.get("prepared_action_id"),
            queue_entry_id=_pr_queued_id,
        )
    except Exception:
        pass
    return resp


def _handle_mso_mode_validation(
    *,
    mso_ctx: _MSOContext,
    perception: dict,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
    session_id: str | None = None,
) -> dict:
    """Mode: validation — read current queue state. Strictly read-only.

    May read/inspect: queue entries, confirmations, policy drafts, authority
    binding drafts, traces, and state. Must NOT call confirm endpoints, policy-
    review mutation, authority-binding mutation, token issuance, PoliceGate,
    AuthorizedPlan, or runner.
    """
    perception_context = perception["perception_context"]
    msg, pending_items = _build_review_queue_status_data()
    try:
        from .mso.police_readiness import get_police_readiness_for_item, build_readiness_summary
        enriched_items = [
            {
                **item,
                "police_readiness": get_police_readiness_for_item(
                    item.get("queue_entry_id", ""),
                    item.get("prepared_action_id", ""),
                ),
            }
            for item in pending_items
        ]
        readiness_summary = build_readiness_summary(pending_items)
    except Exception:  # noqa: BLE001 — fail-soft, diagnostic must not break validation mode
        enriched_items = pending_items
        readiness_summary = {}
    resp = _build_surface_response(
        message=msg,
        domain="MSO",
        surface=surface,
        context_id=context_id,
        identity=identity,
        guard_result=guard_result,
        result_type="surface_response",
        intent="review_queue_status",
        response_source="mso_mode_validation_read_only",
        execution_status="stub",
    )
    resp["pending_review_items"] = enriched_items
    resp["count"] = len(enriched_items)
    resp["readiness_summary"] = readiness_summary
    resp["execution_allowed"] = False
    resp["can_execute_now"] = False
    resp["operation_trace"] = {
        "interaction_mode": "validation",
        "mode_source": mso_ctx.mode_source,
        "agent_seat": mso_ctx.agent_seat,
        "cognition_tier": mso_ctx.cognition_tier,
        "mso_context_warnings": list(mso_ctx.warnings) or None,
        "read_only": True,
        "execution_allowed": False,
        "can_execute_now": False,
    }
    resp["perception_context"] = perception_context
    try:
        from .mso.cognitive_usage_ledger import record_mode_interaction
        record_mode_interaction(
            trace_id=context_id,
            source_component="surface_behavior._handle_mso_mode_validation",
            surface=surface,
            domain="MSO",
            session_id=session_id,
            agent_seat=mso_ctx.agent_seat,
            effective_agent_seat="mso",
            interaction_mode=mso_ctx.interaction_mode,
            cognition_tier=mso_ctx.cognition_tier,
            effective_cognition_tier=mso_ctx.cognition_tier,
            response_source="mso_mode_validation_read_only",
            action="review_queue_status",
        )
    except Exception:
        pass
    return resp


def _handle_mso_mode_orchestration(
    *,
    mso_ctx: _MSOContext,
    perception: dict,
    surface: str,
    context_id: str,
    identity: Any,
    guard_result: Any,
    session_id: str | None = None,
) -> dict:
    """Mode: orchestration — governed-entry narrative. No runner, no token, no execution.

    Explains the current chain limit and guides the operator toward the next
    governed bridge. execution_allowed=False always.
    """
    perception_context = perception["perception_context"]
    msg = (
        "Orchestration mode selected. "
        "The current governed chain reaches AuthorityBindingDraft — "
        "PolicyDecision → CapabilityToken → OperationBinding → AuthorizedPlan → PoliceGate "
        "is not yet complete. "
        "No productive execution has occurred and none is open. "
        "execution_allowed=False, can_execute_now=False. "
        "To advance the chain: confirm a prepared action (via Mission Control), "
        "then request policy review, then authority binding. "
        "Each step requires explicit human confirmation before the next is available."
    )
    resp = _build_surface_response(
        message=msg,
        domain="MSO",
        surface=surface,
        context_id=context_id,
        identity=identity,
        guard_result=guard_result,
        result_type="surface_response",
        intent="orchestration_mode_governed",
        response_source="mso_mode_orchestration_governed",
        execution_status="stub",
    )
    try:
        from .mso.prepared_action_queue import list_pending_confirmable_action_dicts
        from .mso.police_readiness import build_readiness_summary
        _orch_items = list_pending_confirmable_action_dicts()
        orch_readiness_summary = build_readiness_summary(_orch_items)
    except Exception:  # noqa: BLE001 — fail-soft
        orch_readiness_summary = {}
    resp["execution_allowed"] = False
    resp["can_execute_now"] = False
    resp["readiness_summary"] = orch_readiness_summary
    resp["operation_trace"] = {
        "interaction_mode": "orchestration",
        "mode_source": mso_ctx.mode_source,
        "agent_seat": mso_ctx.agent_seat,
        "cognition_tier": mso_ctx.cognition_tier,
        "mso_context_warnings": list(mso_ctx.warnings) or None,
        "chain_status": "authority_binding_draft_only",
        "governed_explanation": True,
        "execution_allowed": False,
        "can_execute_now": False,
    }
    resp["perception_context"] = perception_context
    try:
        from .mso.cognitive_usage_ledger import record_mode_interaction
        record_mode_interaction(
            trace_id=context_id,
            source_component="surface_behavior._handle_mso_mode_orchestration",
            surface=surface,
            domain="MSO",
            session_id=session_id,
            agent_seat=mso_ctx.agent_seat,
            effective_agent_seat="mso",
            interaction_mode=mso_ctx.interaction_mode,
            cognition_tier=mso_ctx.cognition_tier,
            effective_cognition_tier=mso_ctx.cognition_tier,
            response_source="mso_mode_orchestration_governed",
            action="orchestration_mode_governed",
        )
    except Exception:
        pass
    return resp


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
    session_id: str | None = None,
    mso_context: dict | None = None,
) -> dict | None:
    """Return a surface-aware conversational response, or None to continue normal path.

    Returns None for:
    - empty/unknown surface
    - executive inputs on mso_direct when mso_context is absent (backward compat)
    - any input not in the conversational pattern set

    When mso_context is present for surface=mso_direct, the selected
    interaction_mode dominates routing before any text-pattern checks.

    Never changes authority semantics. Never grants execution authority.
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
            response_source="deterministic_conversational",
            execution_status="stub",
        )

    if surface == "assistant_chat":
        if normalized in _ASSISTANT_CHAT_CONVERSATIONAL:
            return _build_surface_response(
                message=_assistant_chat_message(normalized),
                domain="ASSISTANT",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="surface_response",
                intent="conversational_response",
            )

        if normalized in _ASSISTANT_CHAT_STATUS:
            return _build_surface_response(
                message=_assistant_chat_message(normalized),
                domain="SYSTEM",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="status_response",
                intent="status_response",
            )

        if _is_code_context_request(normalized):
            if not _has_code_context(normalized):
                context_request = make_code_repo_context_request(text, context_id)
                return _build_surface_response(
                    message="Necesito el URL del repositorio o una ruta de codigo para revisarlo.",
                    domain="CODE",
                    surface=surface,
                    context_id=context_id,
                    identity=identity,
                    guard_result=guard_result,
                    result_type="clarification",
                    intent="needs_context",
                    missing_fields=["repo_url"],
                    context_request=context_request,
                )

        fin_context_request = maybe_create_fin_context_request(text, normalized, context_id)
        if fin_context_request is not None:
            return _build_surface_response(
                message=fin_context_request["prompted_question"],
                domain="FIN",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="clarification",
                intent="needs_context",
                missing_fields=fin_context_request["missing_fields"],
                context_request=fin_context_request,
            )

        if _is_incomplete_fin_expense(normalized):
            return _build_surface_response(
                message="Necesito el monto para registrar ese gasto.",
                domain="FIN",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="clarification",
                intent="needs_context",
                missing_fields=["amount"],
            )

        try:
            router_result = route_text(_assistant_chat_router_text(text, normalized))
        except Exception:
            return _assistant_chat_router_fail_closed_response(
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
            )

        return _assistant_chat_router_response(
            router_result=router_result,
            normalized=normalized,
            surface=surface,
            context_id=context_id,
            identity=identity,
            guard_result=guard_result,
        )

    if surface == "mso_direct":
        # SPRINT-ALPHA-05.5: When mso_context is present, selected mode dominates.
        # Executive-prefix check does NOT apply — the operator explicitly chose a pipeline.
        # All mode handlers build perception context (grounding/vault/history).
        _mso_ctx = _parse_mso_context(mso_context)
        if _mso_ctx is not None:
            _perception = _build_mso_perception_context(text=text, session_id=session_id)
            if _mso_ctx.interaction_mode == "conversational":
                return _handle_mso_mode_conversational(
                    text=text, mso_ctx=_mso_ctx, perception=_perception,
                    surface=surface, context_id=context_id,
                    identity=identity, guard_result=guard_result,
                    session_id=session_id,
                )
            if _mso_ctx.interaction_mode == "planning":
                return _handle_mso_mode_planning(
                    text=text, normalized=normalized, mso_ctx=_mso_ctx,
                    perception=_perception, surface=surface, context_id=context_id,
                    identity=identity, guard_result=guard_result,
                    session_id=session_id,
                )
            if _mso_ctx.interaction_mode == "validation":
                return _handle_mso_mode_validation(
                    mso_ctx=_mso_ctx, perception=_perception, surface=surface,
                    context_id=context_id, identity=identity, guard_result=guard_result,
                    session_id=session_id,
                )
            if _mso_ctx.interaction_mode == "orchestration":
                return _handle_mso_mode_orchestration(
                    mso_ctx=_mso_ctx, perception=_perception, surface=surface,
                    context_id=context_id, identity=identity, guard_result=guard_result,
                    session_id=session_id,
                )
            # _parse_mso_context always normalizes; this branch is unreachable.

        # ── mso_context absent: existing text-driven path (backward compat) ──────
        if _is_executive(normalized):
            return None
        if normalized in _MSO_STATUS_QUERY_SET:
            _entity_status = _safe_build_mso_entity_status()
            _status_resp = _build_surface_response(
                message=_mso_entity_status_message(_entity_status),
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="status_response",
                intent="mso_entity_status",
                execution_status="not_executed",
                response_source="mso_entity_status_read_model",
            )
            _status_resp["entity_status"] = _entity_status
            _status_resp["used_execution"] = False
            _status_resp["can_execute_now"] = False
            return _status_resp
        if normalized in _MSO_SEAT_CHANGE_SET:
            _change_msg = _mso_seat_change_message(normalized)
            _change_resp = _build_surface_response(
                message=_change_msg,
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="status_response",
                intent="mso_seat_change",
                execution_status="not_executed",
                response_source="mso_seat_change_read_model",
            )
            _change_resp["used_execution"] = False
            _change_resp["can_execute_now"] = False
            _seat_status = _safe_build_mso_seat_status()
            _change_resp["seat_status"] = _seat_status
            return _change_resp
        if normalized in _MSO_DIRECT_CONVERSATIONAL:
            return _build_surface_response(
                message=_mso_conversational_message(normalized),
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                response_source="deterministic_conversational",
                execution_status="stub",
            )
        # SPRINT-ALPHA-05.1: Intercept plan_request BEFORE narrative_runtime so
        # "Prepárame un plan" is governed as plan_request, not LLM freeform.
        # Fail-safe: if route_text or the builder raises, capture the reason and
        # fall through to the narrative path — never raises to the caller.
        _pr_route_error: str | None = None
        try:
            _pr_router = route_text(normalized)
            if _pr_router.get("intent_type") == "plan_request":
                _pr_provider_ctx = _build_plan_request_provider_context()
                _pr_auth_data = _build_plan_request_authority_data(normalized)
                _pr_queued = _pr_auth_data.get("queued_prepared_action") or {}
                # visible_in_mission_control only when a queue entry was actually created
                _pr_queued_id = _pr_queued.get("queue_entry_id")
                _pr_visible = bool(_pr_queued_id)
                _pr_resp = _build_surface_response(
                    message=_plan_request_message(_pr_provider_ctx, _pr_auth_data),
                    domain="ASSISTANT",
                    surface=surface,
                    context_id=context_id,
                    identity=identity,
                    guard_result=guard_result,
                    result_type="surface_response",
                    intent="plan_request",
                )
                _pr_resp["provider_context"] = _pr_provider_ctx
                _pr_resp["proposal_summary"] = _pr_auth_data.get("proposal_summary")
                _pr_resp["authority_preparation"] = _pr_auth_data.get("authority_preparation")
                _pr_resp["confirmable_action"] = _pr_auth_data.get("confirmable_action")
                _pr_resp["queued_prepared_action"] = _pr_queued
                _pr_resp["response_source"] = "mso_plan_request_prepared"
                _pr_resp["execution_status"] = "not_executed"
                _pr_resp["used_execution"] = False
                _pr_resp["operation_trace"] = {
                    "plan_request_prepared": _pr_visible,
                    "prepared_action_id": _pr_queued_id,
                    "confirmation_required": True,
                    "visible_in_mission_control": _pr_visible,
                    "source_surface": "mso_direct",
                    "execution_allowed": False,
                    "can_execute_now": False,
                    "used_execution": False,
                }
                return _pr_resp
        except Exception as _pr_exc:
            _pr_route_error = str(_pr_exc)
        # Deterministic narrative fast-path (Sprint 2)
        try:
            from .mso.narrative_runtime import is_mso_narrative_intent, build_narrative_context_message
            if is_mso_narrative_intent(normalized):
                _msg, _ctx = build_narrative_context_message()
                return _build_surface_response(
                    message=_msg,
                    domain="MSO",
                    surface=surface,
                    context_id=context_id,
                    identity=identity,
                    guard_result=guard_result,
                    result_type="surface_response",
                    intent="mso_narrative_status",
                    response_source="deterministic_narrative",
                    execution_status="stub",
                    narrative_context=_ctx,
                )
        except Exception:
            pass
        # Cognitive generation path (Sprint 4) — provider-backed with Vault, fails closed
        try:
            import time as _time
            grounding = build_mso_grounding_context()
            vault_ctx = _get_vault_context(query=text)

            # Bounded session history — fail-closed: errors return empty history
            try:
                session_hist = _get_session_history(session_id)
            except Exception as _hist_exc:
                session_hist = {
                    "available": False, "turns": [], "turns_used": 0,
                    "source": "unavailable", "truncated": False,
                    "warnings": [f"history retrieval failed: {_hist_exc}"],
                }

            grounding_with_vault = {
                **grounding,
                "vault_context": vault_ctx,
                "session_history": session_hist,
            }
            _start_time = _time.perf_counter()
            _latency_ms: int | None = None
            _provider_err = None
            try:
                _hist_turns = (
                    session_hist["turns"]
                    if session_hist.get("available") and session_hist.get("turns")
                    else None
                )
                if _hist_turns:
                    provider_resp = _call_mso_cognitive(
                        grounding_with_vault, text, history=_hist_turns
                    )
                else:
                    provider_resp = _call_mso_cognitive(grounding_with_vault, text)
                _latency_ms = int((_time.perf_counter() - _start_time) * 1000)
                if provider_resp.get("status") == "ok" and provider_resp.get("text", "").strip():
                    provider_metadata = provider_resp.get("metadata") or {}
                    cognitive_trace = {
                        "response_source": "llm_economic",
                        "execution_status": "real",
                        "provider_used": provider_resp.get("provider_name", ""),
                        "model_used": provider_resp.get("model_name", ""),
                        "cognitive_generation": True,
                        "fallback_used": False,
                        "fallback_reason": None,
                        "latency_ms": _latency_ms,
                        "tokens_in": provider_metadata.get("tokens_in"),
                        "tokens_out": provider_metadata.get("tokens_out"),
                        "execution_allowed": False,
                        "can_execute_now": False,
                        "vault_enabled": vault_ctx.get("enabled", False),
                        "vault_chunks_used": vault_ctx.get("vault_chunks_used", 0),
                        "vault_sources": vault_ctx.get("vault_sources", []),
                        "vault_retrieval_method": vault_ctx.get("retrieval_method", "keyword_topk"),
                        "vault_warnings": vault_ctx.get("warnings", []),
                        "vault_truncated": vault_ctx.get("truncated", False),
                        "vault_packs_consulted": vault_ctx.get("packs_consulted", []),
                        "history_available": session_hist.get("available", False),
                        "history_turns_used": session_hist.get("turns_used", 0),
                        "history_source": session_hist.get("source", "none"),
                        "history_truncated": session_hist.get("truncated", False),
                        "history_warnings": session_hist.get("warnings", []),
                        "synthesis_mode": "economic",
                        "perception_frame_version": grounding.get("version", ""),
                    }
                    try:
                        from .mso.cognitive_usage_ledger import record_provider_call
                        record_provider_call(
                            trace_id=context_id,
                            source_component="surface_behavior.legacy_mso_direct",
                            surface=surface,
                            domain="MSO",
                            session_id=session_id,
                            provider_used=provider_resp.get("provider_name"),
                            model_used=provider_resp.get("model_name"),
                            tokens_in=provider_metadata.get("tokens_in"),
                            tokens_out=provider_metadata.get("tokens_out"),
                            latency_ms=_latency_ms,
                            action="mso_cognitive_response",
                            response_source="llm_economic",
                        )
                    except Exception:
                        pass
                    return _build_surface_response(
                        message=provider_resp["text"].strip(),
                        domain="MSO",
                        surface=surface,
                        context_id=context_id,
                        identity=identity,
                        guard_result=guard_result,
                        result_type="surface_response",
                        intent="mso_cognitive_response",
                        response_source="llm_economic",
                        execution_status="real",
                        provider_used=provider_resp.get("provider_name", ""),
                        model_used=provider_resp.get("model_name", ""),
                        cognitive_generation=True,
                        fallback_used=False,
                        narrative_context={
                            **grounding_with_vault,
                            "execution_allowed": False,
                            "can_execute_now": False,
                        },
                        latency_ms=_latency_ms,
                        tokens_in=provider_metadata.get("tokens_in"),
                        tokens_out=provider_metadata.get("tokens_out"),
                        cognitive_trace=cognitive_trace,
                    )
                else:
                    _provider_err = provider_resp.get("error") or provider_resp.get("reason") or "unusable provider response"
            except Exception as e:
                _latency_ms = int((_time.perf_counter() - _start_time) * 1000)
                _provider_err = str(e)

            # Provider call failed or returned unusable response — fall back to narrative.
            # If plan_request routing also failed earlier, thread that reason in too.
            _msg, _ctx = build_narrative_context_message()
            _fallback_source = "provider_unavailable" if "key not configured" in str(_provider_err).lower() else "deterministic_fallback"
            _combined_fallback_reason = "; ".join(filter(None, [_pr_route_error, _provider_err])) or None
            try:
                from .mso.cognitive_usage_ledger import record_provider_fallback
                record_provider_fallback(
                    trace_id=context_id,
                    source_component="surface_behavior.legacy_mso_direct",
                    surface=surface,
                    domain="MSO",
                    session_id=session_id,
                    response_source=_fallback_source,
                    fallback_reason=_combined_fallback_reason,
                    latency_ms=_latency_ms,
                    action="mso_narrative_status",
                )
            except Exception:
                pass
            return _build_surface_response(
                message=_msg,
                domain="MSO",
                surface=surface,
                context_id=context_id,
                identity=identity,
                guard_result=guard_result,
                result_type="surface_response",
                intent="mso_narrative_status",
                response_source=_fallback_source,
                execution_status="unavailable",
                fallback_used=True,
                fallback_reason=_combined_fallback_reason,
                narrative_context=_ctx,
                latency_ms=_latency_ms,
            )
        except Exception:
            pass
        return None

    return None
