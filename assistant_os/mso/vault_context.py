"""Fail-safe Vault context builder for MSO Economic Mode.

build_vault_context() never raises — all errors produce a disabled context
with warnings populated. Safe to call in the hot path of mso_direct
cognitive generation.
"""

from __future__ import annotations

from pathlib import Path

from assistant_os.config import ASSISTANT_OS_VAULT_PATH
from assistant_os.mso.vault import keyword_search

_ECONOMIC_TOP_K: int = 3
_ECONOMIC_TOKEN_BUDGET: int = 800


def build_vault_context(
    query: str,
    mode: str = "economic",
    top_k: int | None = None,
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
        }

    Never raises. vault_path missing or invalid → enabled=False, warnings set.
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

    try:
        chunks = keyword_search(
            vault_path=vault_path,
            query=query,
            top_k=effective_top_k,
            token_budget=_ECONOMIC_TOKEN_BUDGET,
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
            }
            for c in chunks
        ],
        "vault_sources": [c.note_path for c in chunks],
        "vault_chunks_used": len(chunks),
        "token_budget_used": total_chars // 4,
        "truncated": truncated,
        "warnings": [],
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
    }
