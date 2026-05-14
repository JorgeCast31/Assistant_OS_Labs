"""Fail-safe Vault context builder for MSO Economic Mode.

build_vault_context() never raises — all errors produce a disabled context
with warnings populated. Safe to call in the hot path of mso_direct
cognitive generation.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from assistant_os.config import ASSISTANT_OS_VAULT_PATH
from assistant_os.mso.vault import keyword_search

_ECONOMIC_TOP_K: int = 3
_ECONOMIC_TOKEN_BUDGET: int = 800

# ---------------------------------------------------------------------------
# Pack signal heuristics
# ---------------------------------------------------------------------------

_PACK_SIGNALS: dict[str, list[str]] = {
    "CODE": [
        "codigo", "code", "repo", "sprint", "refactor", "bug", "test", "deploy",
        "backend", "frontend", "api", "arquitectura", "modulo", "module", "clase",
        "function", "funcion", "pipeline", "ci", "cd", "git", "branch", "commit",
        "merge", "pr", "pull request", "implementa", "implementar", "desarrollo",
        "develop", "build", "lint", "typecheck", "importa", "importar", "script",
    ],
    "HEALTH": [
        "salud", "health", "sueno", "sueño", "sleep", "energia", "energia",
        "ansiedad", "anxiety", "stress", "estres", "dolor", "pain", "ejercicio",
        "exercise", "medico", "doctor", "medicacion", "medicacion", "bienestar",
        "wellness", "mental", "cuerpo", "body", "nutricion", "nutricion", "dieta",
        "diet", "descanso", "rest", "fatiga", "fatigue",
    ],
    "FIN": [
        "presupuesto", "budget", "gasto", "gastos", "expense", "expenses",
        "dinero", "money", "finanzas", "finance", "ingreso", "ingresos",
        "income", "ahorro", "savings", "deuda", "debt", "inversion", "inversión",
        "investment", "factura", "invoice", "pago", "payment", "banco", "bank",
        "cuenta", "account", "balance", "patrimonio",
    ],
    "IPROTA": [
        "iprota", "canon", "identidad", "identity", "protocolo", "protocol",
        "soberania", "soberanía", "sovereignty", "ritual", "doctrina", "doctrine",
        "principio", "principle", "valor", "axioma", "axiom", "manifiesto",
        "manifesto", "contrato", "contract", "pacto", "pact",
    ],
    "WORK": [
        "tarea", "task", "tareas", "pendiente", "pending", "lab", "laboratorio",
        "proyecto", "project", "reunion", "reunión", "meeting", "deadline",
        "entregable", "deliverable", "agenda", "planificacion", "planificación",
        "planning", "objetivo", "goal", "meta", "hito", "milestone", "sprint",
        "equipo", "team", "colaboracion", "colaboración", "coordination",
    ],
    "ENERGY": [
        "energia", "energía", "energy", "productividad", "productivity",
        "rutina", "routine", "habito", "hábito", "habit", "momentum", "flujo",
        "flow", "enfoque", "focus", "concentracion", "concentración",
        "concentration", "motivacion", "motivación", "motivation", "rendimiento",
        "performance", "pico", "peak", "cronobiologia", "ritmo", "ritmo",
    ],
    "PRO_DIAG": [
        "diagnostico", "diagnóstico", "diagnostic", "riesgo", "risk",
        "empresarial", "business", "empresa", "company", "startup", "venture",
        "estrategia", "strategy", "analisis", "análisis", "analysis",
        "evaluacion", "evaluación", "evaluation", "market", "mercado",
        "oportunidad", "opportunity", "amenaza", "threat", "fortaleza",
        "debilidad", "weakness", "swot", "foda",
    ],
}


def _normalize_for_pack(text: str) -> str:
    """Strip diacritics and lowercase for robust signal matching."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()


def infer_query_packs(
    query: str,
    surface: str | None = None,
    domain: str | None = None,
) -> list[str] | None:
    """Heuristic: infer relevant domain packs from the query text.

    Returns a sorted list of pack names (always including SYSTEM when any domain
    pack is matched), or None when no domain-specific signals are found
    (indicating flat retrieval should be used).

    Never raises.
    """
    try:
        if not query or not query.strip():
            return None

        normalized = _normalize_for_pack(query)
        words = set(normalized.split())

        matched: set[str] = set()

        for pack_name, signals in _PACK_SIGNALS.items():
            for signal in signals:
                norm_signal = _normalize_for_pack(signal)
                if norm_signal in normalized or norm_signal in words:
                    matched.add(pack_name)
                    break

        if not matched:
            return None

        matched.add("SYSTEM")
        return sorted(matched)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_vault_context(
    query: str,
    mode: str = "economic",
    top_k: int | None = None,
    allowed_packs: list[str] | None = None,
    domain_hints: list[str] | None = None,
) -> dict:
    """Build a read-only Vault semantic context dict for injection into MSO prompts.

    Returned shape::

        {
          "enabled": bool,
          "query": str,
          "retrieval_method": "keyword_topk",
          "chunks": [...],
          "vault_sources": [...],
          "vault_chunks_used": int,
          "token_budget_used": int,
          "truncated": bool,
          "warnings": [...],
          "pack_filter_active": bool,
          "packs_consulted": [...],
          "unclassified_included": bool,
        }

    Never raises. vault_path missing or invalid → enabled=False, warnings set.

    When allowed_packs is provided, pack filtering is applied.
    When allowed_packs is None but domain_hints are given, domain_hints act as
    the pack filter. SYSTEM is always included in any filter.
    Unclassified notes (pack=None) always pass through any filter.
    """
    vault_path = ASSISTANT_OS_VAULT_PATH

    if not vault_path:
        return _disabled(query)

    if not Path(vault_path).is_dir():
        return {
            **_disabled(query),
            "warnings": [
                f"ASSISTANT_OS_VAULT_PATH is not a valid directory: {vault_path!r}"
            ],
        }

    effective_top_k = top_k if top_k is not None else _ECONOMIC_TOP_K

    # Determine effective pack filter
    effective_packs: list[str] | None = None
    if allowed_packs:
        effective_packs = allowed_packs
    elif domain_hints:
        effective_packs = domain_hints

    # If no explicit pack filter, try heuristic inference (fail-closed: exception → flat)
    if effective_packs is None:
        try:
            inferred = infer_query_packs(query)
            effective_packs = inferred  # may still be None → flat retrieval
        except Exception:
            effective_packs = None

    pack_filter_active = bool(effective_packs)

    if pack_filter_active:
        packs_consulted = sorted(
            frozenset(p.upper() for p in effective_packs) | {"SYSTEM"}
        )
    else:
        packs_consulted = ["ALL"]

    try:
        chunks = keyword_search(
            vault_path=vault_path,
            query=query,
            top_k=effective_top_k,
            token_budget=_ECONOMIC_TOKEN_BUDGET,
            allowed_packs=effective_packs if effective_packs else None,
        )
    except Exception as exc:
        return {
            **_disabled(query),
            "warnings": [f"Vault retrieval error: {exc}"],
        }

    total_chars = sum(len(c.content) for c in chunks)
    char_budget = _ECONOMIC_TOKEN_BUDGET * 4
    truncated = len(chunks) > 0 and total_chars >= char_budget * 0.9

    return {
        "enabled": True,
        "query": query,
        "retrieval_method": "keyword_topk",
        "chunks": [
            {
                "note_path": c.note_path,
                "title": c.title,
                "tags": c.tags,
                "frontmatter": c.frontmatter,
                "content": c.content,
                "score": c.score,
                "pack": c.pack,
            }
            for c in chunks
        ],
        "vault_sources": [c.note_path for c in chunks],
        "vault_chunks_used": len(chunks),
        "token_budget_used": total_chars // 4,
        "truncated": truncated,
        "warnings": [],
        "pack_filter_active": pack_filter_active,
        "packs_consulted": packs_consulted,
        "unclassified_included": True,
    }


def _disabled(query: str) -> dict:
    return {
        "enabled": False,
        "query": query,
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "token_budget_used": 0,
        "truncated": False,
        "warnings": [],
        "pack_filter_active": False,
        "packs_consulted": [],
        "unclassified_included": True,
    }
