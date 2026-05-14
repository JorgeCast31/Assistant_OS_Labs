"""Tests for Vault Context Layer — Alpha Phase 3.

Covers vault.py (tests 1-7), vault_context.py (tests 8-9),
and build_mso_chat_system_prompt vault section (tests 11-12).
"""

from __future__ import annotations

import pytest
from pathlib import Path

from assistant_os.mso.vault import (
    VaultChunk,
    VaultNote,
    VaultReader,
    parse_frontmatter,
    keyword_search,
    list_markdown_notes,
    read_note,
)


# ---------------------------------------------------------------------------
# Test 1: parse_frontmatter parses valid frontmatter
# ---------------------------------------------------------------------------

def test_parse_frontmatter_valid():
    text = (
        "---\n"
        "title: My Note\n"
        "status: stable\n"
        "domain: economics\n"
        "tags: [budget, planning]\n"
        "retrieval_weight: 0.9\n"
        "---\n"
        "\nBody here."
    )
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "My Note"
    assert fm["status"] == "stable"
    assert fm["domain"] == "economics"
    assert fm["tags"] == ["budget", "planning"]
    assert float(fm["retrieval_weight"]) == pytest.approx(0.9)
    assert body.strip() == "Body here."


# ---------------------------------------------------------------------------
# Test 2: parse_frontmatter tolerates missing frontmatter
# ---------------------------------------------------------------------------

def test_parse_frontmatter_missing():
    text = "Just a plain note with no frontmatter."
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_malformed_delimiter():
    text = "-- not frontmatter\ntitle: Foo\n--\nBody"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_block_list():
    text = (
        "---\n"
        "title: Block Tags\n"
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "---\n"
        "Body"
    )
    fm, body = parse_frontmatter(text)
    assert fm["tags"] == ["alpha", "beta"]
    assert body.strip() == "Body"


# ---------------------------------------------------------------------------
# Test 3: VaultReader lists only .md files
# ---------------------------------------------------------------------------

def test_vault_reader_lists_markdown_only(tmp_path: Path):
    (tmp_path / "note1.md").write_text("# Note 1")
    (tmp_path / "note2.md").write_text("# Note 2")
    (tmp_path / "image.png").write_bytes(b"PNG")
    (tmp_path / "data.json").write_text("{}")
    reader = VaultReader(str(tmp_path))
    notes = reader.list_notes()
    assert len(notes) == 2
    for n in notes:
        assert isinstance(n, VaultNote)


def test_vault_reader_ignores_hidden_dirs(tmp_path: Path):
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "config.md").write_text("# Hidden")
    (tmp_path / "visible.md").write_text("# Visible")
    reader = VaultReader(str(tmp_path))
    notes = reader.list_notes()
    assert len(notes) == 1
    assert notes[0].path.name == "visible.md"


# ---------------------------------------------------------------------------
# Test 4: deprecated notes excluded from retrieval by default
# ---------------------------------------------------------------------------

def test_deprecated_notes_excluded(tmp_path: Path):
    (tmp_path / "active.md").write_text(
        "---\ntitle: Active\nstatus: stable\n---\nsome content"
    )
    (tmp_path / "old.md").write_text(
        "---\ntitle: Old\nstatus: deprecated\n---\nsome content"
    )
    chunks = keyword_search(str(tmp_path), query="some content", top_k=10)
    titles = [c.title for c in chunks]
    assert "Active" in titles
    assert "Old" not in titles


def test_deprecated_notes_included_when_opted_in(tmp_path: Path):
    (tmp_path / "old.md").write_text(
        "---\ntitle: Old\nstatus: deprecated\n---\nsome content"
    )
    chunks = keyword_search(
        str(tmp_path), query="some content", top_k=10, exclude_deprecated=False
    )
    titles = [c.title for c in chunks]
    assert "Old" in titles


# ---------------------------------------------------------------------------
# Test 5: stable notes score higher than draft/no-frontmatter
# ---------------------------------------------------------------------------

def test_stable_notes_score_higher_than_draft(tmp_path: Path):
    (tmp_path / "stable.md").write_text(
        "---\ntitle: Stable Note\nstatus: stable\n---\nbudget planning information"
    )
    (tmp_path / "draft.md").write_text(
        "---\ntitle: Draft Note\nstatus: draft\n---\nbudget planning information"
    )
    chunks = keyword_search(str(tmp_path), query="budget planning information", top_k=10)
    assert len(chunks) == 2
    stable_chunk = next(c for c in chunks if c.title == "Stable Note")
    draft_chunk = next(c for c in chunks if c.title == "Draft Note")
    assert stable_chunk.score > draft_chunk.score


def test_no_frontmatter_note_scores_lower_than_stable(tmp_path: Path):
    (tmp_path / "stable.md").write_text(
        "---\ntitle: Stable\nstatus: stable\n---\ncognitive content here"
    )
    (tmp_path / "plain.md").write_text("cognitive content here")
    chunks = keyword_search(str(tmp_path), query="cognitive content here", top_k=10)
    assert len(chunks) == 2
    stable_chunk = next(c for c in chunks if c.title == "Stable")
    plain_chunk = next(c for c in chunks if c.title != "Stable")
    assert stable_chunk.score >= plain_chunk.score


# ---------------------------------------------------------------------------
# Test 6: keyword_search returns top_k bounded chunks
# ---------------------------------------------------------------------------

def test_keyword_search_top_k(tmp_path: Path):
    for i in range(7):
        (tmp_path / f"note{i}.md").write_text(
            f"---\ntitle: Note {i}\nstatus: stable\n---\nkeyword content here"
        )
    chunks = keyword_search(str(tmp_path), query="keyword content here", top_k=3)
    assert len(chunks) <= 3


def test_keyword_search_no_match_returns_empty(tmp_path: Path):
    (tmp_path / "note.md").write_text("---\ntitle: Note\nstatus: stable\n---\nfoo bar baz")
    chunks = keyword_search(str(tmp_path), query="totally unrelated xyzzy", top_k=5)
    assert chunks == []


# ---------------------------------------------------------------------------
# Test 7: token budget truncates content
# ---------------------------------------------------------------------------

def test_token_budget_truncates_content(tmp_path: Path):
    long_content = "word " * 500  # ~2500 chars
    (tmp_path / "big.md").write_text(
        f"---\ntitle: Big Note\nstatus: stable\n---\n{long_content}"
    )
    # budget = 20 tokens → ~80 chars budget
    chunks = keyword_search(str(tmp_path), query="word", top_k=1, token_budget=20)
    assert len(chunks) == 1
    # Content must fit within budget (4 chars/token * 20 = 80, with some tolerance)
    assert len(chunks[0].content) <= 100


def test_keyword_search_chunk_has_score(tmp_path: Path):
    (tmp_path / "note.md").write_text(
        "---\ntitle: Scored\nstatus: stable\n---\ntest content"
    )
    chunks = keyword_search(str(tmp_path), query="test content", top_k=5)
    assert len(chunks) == 1
    assert isinstance(chunks[0].score, float)
    assert chunks[0].score > 0.0


# ---------------------------------------------------------------------------
# Tests 8-9: build_vault_context (added after vault_context.py is created)
# ---------------------------------------------------------------------------

from assistant_os.mso.vault_context import build_vault_context


def test_build_vault_context_disabled_when_path_empty(monkeypatch):
    """Test 8: disabled context when ASSISTANT_OS_VAULT_PATH is unset."""
    import assistant_os.mso.vault_context as vc_mod
    monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "")
    result = build_vault_context("some query")
    assert result["enabled"] is False
    assert result["vault_chunks_used"] == 0
    assert result["chunks"] == []
    assert result["vault_sources"] == []
    assert result["truncated"] is False
    assert isinstance(result["warnings"], list)


def test_build_vault_context_warning_when_path_invalid(monkeypatch):
    """Test 9: warning populated, no exception, when vault path is not a dir."""
    import assistant_os.mso.vault_context as vc_mod
    monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "/nonexistent/path/xyzzy123")
    result = build_vault_context("some query")
    assert result["enabled"] is False
    assert len(result["warnings"]) > 0
    assert result["vault_chunks_used"] == 0


def test_build_vault_context_returns_chunks_when_vault_valid(tmp_path, monkeypatch):
    """build_vault_context returns enabled=True and chunks when vault is valid."""
    (tmp_path / "doc.md").write_text(
        "---\ntitle: Economic Framework\nstatus: stable\n---\neconomic budget planning"
    )
    import assistant_os.mso.vault_context as vc_mod
    monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
    result = build_vault_context("economic budget planning")
    assert result["enabled"] is True
    assert result["vault_chunks_used"] >= 1
    assert result["retrieval_method"] == "keyword_topk"
    assert isinstance(result["chunks"], list)
    assert result["chunks"][0]["title"] == "Economic Framework"
    assert result["chunks"][0]["score"] > 0.0


def test_build_vault_context_shape(monkeypatch):
    """build_vault_context always returns the required keys."""
    import assistant_os.mso.vault_context as vc_mod
    monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "")
    result = build_vault_context("any query")
    required_keys = {
        "enabled", "query", "retrieval_method", "chunks",
        "vault_sources", "vault_chunks_used", "token_budget_used",
        "truncated", "warnings",
    }
    assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests 11-12: build_mso_chat_system_prompt vault section
# ---------------------------------------------------------------------------

from assistant_os.mso.prompts import build_mso_chat_system_prompt


def _make_grounding(vault_context=None) -> dict:
    return {
        "operational_mode": "TEST_MODE",
        "seat_provider": "test-provider",
        "prepared_actions_count": 0,
        "next_safe_step": "none",
        "authority_posture": "test chain",
        "limitations": "You cannot execute.",
        "vault_context": vault_context,
    }


def test_prompt_includes_vault_section_when_chunks_exist(tmp_path, monkeypatch):
    """Test 11: prompt includes Vault section and source titles when chunks present."""
    import assistant_os.mso.vault_context as vc_mod
    monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
    (tmp_path / "budget.md").write_text(
        "---\ntitle: Budget Framework\nstatus: stable\n---\nBudget planning doctrine."
    )
    vault_ctx = build_vault_context("budget planning")
    grounding = _make_grounding(vault_context=vault_ctx)
    prompt = build_mso_chat_system_prompt(grounding)
    assert "VAULT SEMANTIC CONTEXT" in prompt
    assert "Budget Framework" in prompt
    assert "Retrieval enabled: yes" in prompt


def test_prompt_vault_disabled_does_not_raise():
    """Test 12: prompt indicates vault disabled/empty without raising."""
    disabled_ctx = {
        "enabled": False,
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "warnings": [],
    }
    grounding = _make_grounding(vault_context=disabled_ctx)
    prompt = build_mso_chat_system_prompt(grounding)
    assert "VAULT SEMANTIC CONTEXT" in prompt
    assert "Retrieval enabled: no" in prompt


def test_prompt_vault_none_does_not_raise():
    """Prompt must tolerate vault_context=None."""
    grounding = _make_grounding(vault_context=None)
    prompt = build_mso_chat_system_prompt(grounding)
    assert isinstance(prompt, str)
    assert len(prompt) > 0
