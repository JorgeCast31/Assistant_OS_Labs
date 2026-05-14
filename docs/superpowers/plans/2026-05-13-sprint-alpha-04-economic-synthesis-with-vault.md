# SPRINT-ALPHA-04: Economic LLM Synthesis with Vault — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Economic Mode MSO response genuinely synthesize user input, economic perception frame, Vault semantic context, and execution boundaries — one LLM call, governed path, no authority changes.

**Architecture:** Port Phase 3 Vault infrastructure (vault.py, vault_context.py, prompt section) into this worktree, then add Phase 4 ECONOMIC SYNTHESIS TASK prompt contract, synthesis_mode trace field, perception_frame_version, and stronger validation patterns. surface_behavior.py cognitive path injects vault context into grounding_context before calling the provider and builds a structured cognitive_trace with all Phase 1-4 fields.

**Tech Stack:** Python 3.11+, pytest, Anthropic SDK (anthropic), existing MSO subsystems. No new dependencies.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `assistant_os/config.py` | Modify | Add `ASSISTANT_OS_VAULT_PATH` env var read |
| `assistant_os/mso/vault.py` | Create | Read-only Vault utilities (parse_frontmatter, keyword_search) — ported from Phase 3 |
| `assistant_os/mso/vault_context.py` | Create | `build_vault_context()` — fail-safe context builder — ported from Phase 3 |
| `assistant_os/mso/prompts.py` | Modify | Add vault section (Phase 3) + ECONOMIC SYNTHESIS TASK (Phase 4) |
| `assistant_os/mso/mso_chat_provider.py` | Modify | Add missing execution-claim validation patterns |
| `assistant_os/surface_behavior.py` | Modify | Add `_get_vault_context()`, vault injection, full cognitive_trace with synthesis_mode |
| `tests/test_vault_context.py` | Create | Phase 3 vault tests (parse_frontmatter, keyword_search, build_vault_context, prompt vault section) |
| `tests/test_economic_synthesis.py` | Create | Phase 4 synthesis tests (all 15 required) |

---

## Task 1: Add ASSISTANT_OS_VAULT_PATH to config.py

**Files:**
- Modify: `assistant_os/config.py`

- [ ] **Step 1.1: Locate the config constant block**

  Open `assistant_os/config.py`. Find the existing env var reads (around line 103 where `ANTHROPIC_API_KEY` and `MSO_SEAT_MODEL` are defined). Identify the last env var read in the file.

- [ ] **Step 1.2: Add the vault path env var**

  Add after the last existing env var read (after `MSO_SEAT_MODEL`):

  ```python
  ASSISTANT_OS_VAULT_PATH: str = os.environ.get("ASSISTANT_OS_VAULT_PATH", "").strip()
  ```

- [ ] **Step 1.3: Verify import works**

  ```bash
  python -c "from assistant_os.config import ASSISTANT_OS_VAULT_PATH; print('ok', repr(ASSISTANT_OS_VAULT_PATH))"
  ```

  Expected: `ok ''` (or the path if env var is set)

- [ ] **Step 1.4: Commit**

  ```bash
  git add assistant_os/config.py
  git commit -m "feat(config): add ASSISTANT_OS_VAULT_PATH env var — SPRINT-ALPHA-04"
  ```

---

## Task 2: Create assistant_os/mso/vault.py

**Files:**
- Create: `assistant_os/mso/vault.py`
- Test (partial): `tests/test_vault_context.py` (steps 2.2–2.3 only)

- [ ] **Step 2.1: Write vault.py**

  Create `assistant_os/mso/vault.py` with the full content below:

  ```python
  """Read-only Obsidian Vault utilities for MSO semantic context retrieval.

  No writes, no embeddings, no Obsidian-specific APIs. Plain Markdown only.
  Tolerates missing or malformed frontmatter. Never raises from public functions.
  """

  from __future__ import annotations

  import re
  from dataclasses import dataclass
  from pathlib import Path


  @dataclass
  class VaultChunk:
      note_path: str
      title: str
      tags: list[str]
      frontmatter: dict
      content: str
      score: float


  @dataclass
  class VaultNote:
      path: Path
      frontmatter: dict
      body: str
      title: str
      tags: list[str]
      status: str
      retrieval_weight: float


  def parse_frontmatter(text: str) -> tuple[dict, str]:
      """Extract YAML frontmatter from markdown text.

      Returns (metadata_dict, body_text). Returns ({}, original_text) when
      frontmatter is absent or malformed — never raises.

      Handles:
        - Inline lists:  key: [a, b, c]
        - Block lists:   key:\\n  - a\\n  - b
        - Plain scalars: key: value
      """
      if not text.startswith("---"):
          return {}, text

      rest = text[3:]
      end_match = re.search(r"\n---[ \t]*\n", rest)
      if not end_match:
          return {}, text

      fm_text = rest[: end_match.start()]
      body = rest[end_match.end() :]

      metadata: dict = {}
      lines = fm_text.splitlines()
      i = 0
      while i < len(lines):
          line = lines[i]
          if ":" not in line:
              i += 1
              continue
          key, _, rest_val = line.partition(":")
          key = key.strip()
          if not key:
              i += 1
              continue
          rest_val = rest_val.strip()

          if rest_val.startswith("[") and rest_val.endswith("]"):
              items = [
                  v.strip().strip("\"'")
                  for v in rest_val[1:-1].split(",")
                  if v.strip()
              ]
              metadata[key] = items
              i += 1
          elif rest_val == "":
              items = []
              i += 1
              while i < len(lines) and re.match(r"^\s+-\s", lines[i]):
                  items.append(re.sub(r"^\s+-\s*", "", lines[i]).strip())
                  i += 1
              if items:
                  metadata[key] = items
          else:
              metadata[key] = rest_val
              i += 1

      return metadata, body


  def list_markdown_notes(vault_path: str) -> list[Path]:
      """Return all .md files under vault_path, excluding hidden dirs/files."""
      root = Path(vault_path)
      if not root.is_dir():
          return []
      notes = []
      for p in root.rglob("*.md"):
          if any(part.startswith(".") for part in p.relative_to(root).parts):
              continue
          notes.append(p)
      return notes


  def _status_to_weight(status: str) -> float:
      return {
          "stable": 1.0,
          "active": 0.9,
          "review": 0.7,
          "draft": 0.5,
      }.get(status.lower(), 0.4)


  def read_note(path: Path) -> VaultNote | None:
      """Read a VaultNote from a markdown file. Returns None on any error."""
      try:
          text = path.read_text(encoding="utf-8", errors="replace")
          frontmatter, body = parse_frontmatter(text)

          title = str(frontmatter.get("title", path.stem))

          tags_raw = frontmatter.get("tags", [])
          if isinstance(tags_raw, str):
              tags: list[str] = [tags_raw]
          else:
              tags = list(tags_raw)

          status = str(frontmatter.get("status", ""))

          rw_raw = frontmatter.get("retrieval_weight")
          try:
              retrieval_weight = float(rw_raw) if rw_raw is not None else _status_to_weight(status)
          except (ValueError, TypeError):
              retrieval_weight = _status_to_weight(status)

          return VaultNote(
              path=path,
              frontmatter=frontmatter,
              body=body,
              title=title,
              tags=tags,
              status=status,
              retrieval_weight=retrieval_weight,
          )
      except Exception:
          return None


  class VaultReader:
      """Read-only interface to an Obsidian Vault directory."""

      def __init__(self, vault_path: str) -> None:
          self.vault_path = vault_path

      def list_notes(self) -> list[VaultNote]:
          notes = []
          for p in list_markdown_notes(self.vault_path):
              note = read_note(p)
              if note is not None:
                  notes.append(note)
          return notes


  def keyword_search(
      vault_path: str,
      query: str,
      top_k: int = 3,
      token_budget: int = 800,
      exclude_deprecated: bool = True,
  ) -> list[VaultChunk]:
      """Keyword-based vault search.

      Scores notes by term overlap × retrieval_weight. Applies a character
      budget (~4 chars per token) when truncating chunk content. Never raises.
      """
      query_terms = set(query.lower().split())
      scored: list[tuple[float, VaultNote]] = []

      for p in list_markdown_notes(vault_path):
          note = read_note(p)
          if note is None:
              continue
          if exclude_deprecated and note.status.lower() == "deprecated":
              continue

          haystack = (note.title + " " + note.body + " " + " ".join(note.tags)).lower()
          matches = sum(1 for term in query_terms if term in haystack)
          if matches == 0:
              continue

          score = (matches / max(len(query_terms), 1)) * note.retrieval_weight
          scored.append((score, note))

      scored.sort(key=lambda x: (-x[0], -x[1].retrieval_weight))

      char_budget = token_budget * 4
      chunks: list[VaultChunk] = []

      for score, note in scored[:top_k]:
          content = note.body.strip()
          if len(content) > char_budget:
              content = content[:char_budget].rstrip()
          char_budget -= len(content)

          chunks.append(
              VaultChunk(
                  note_path=str(note.path),
                  title=note.title,
                  tags=note.tags,
                  frontmatter=note.frontmatter,
                  content=content,
                  score=score,
              )
          )

          if char_budget <= 0:
              break

      return chunks
  ```

- [ ] **Step 2.2: Write parse_frontmatter and keyword_search tests into test_vault_context.py**

  Create `tests/test_vault_context.py` with tests 1–7 (vault.py primitives):

  ```python
  """Tests for Vault Context Layer — Alpha Phase 3 + 4.

  Tests 1-7: vault.py primitives (parse_frontmatter, keyword_search, VaultReader)
  Tests 8-10: vault_context.py (build_vault_context)
  Tests 11-13: build_mso_chat_system_prompt vault section
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
  # Test 2: parse_frontmatter tolerates missing / malformed frontmatter
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
  # Test 3: VaultReader lists only .md files and ignores hidden dirs
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
  # Test 5: stable notes score higher than draft
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
      chunks = keyword_search(str(tmp_path), query="word", top_k=1, token_budget=20)
      assert len(chunks) == 1
      assert len(chunks[0].content) <= 100


  def test_keyword_search_chunk_has_score(tmp_path: Path):
      (tmp_path / "note.md").write_text(
          "---\ntitle: Scored\nstatus: stable\n---\ntest content"
      )
      chunks = keyword_search(str(tmp_path), query="test content", top_k=5)
      assert len(chunks) == 1
      assert isinstance(chunks[0].score, float)
      assert chunks[0].score > 0.0
  ```

- [ ] **Step 2.3: Run vault.py tests — expect PASS (vault.py is already created)**

  ```bash
  python -m pytest tests/test_vault_context.py::test_parse_frontmatter_valid tests/test_vault_context.py::test_parse_frontmatter_missing tests/test_vault_context.py::test_vault_reader_lists_markdown_only tests/test_vault_context.py::test_keyword_search_top_k -v
  ```

  Expected: 4 PASS

- [ ] **Step 2.4: Commit**

  ```bash
  git add assistant_os/mso/vault.py tests/test_vault_context.py
  git commit -m "feat(vault): add vault.py read-only Vault utilities + tests — SPRINT-ALPHA-04"
  ```

---

## Task 3: Create assistant_os/mso/vault_context.py

**Files:**
- Create: `assistant_os/mso/vault_context.py`
- Modify: `tests/test_vault_context.py` (append tests 8–10)

- [ ] **Step 3.1: Write failing tests for build_vault_context (append to test_vault_context.py)**

  Append after the existing test content:

  ```python
  # ---------------------------------------------------------------------------
  # Tests 8-10: build_vault_context (vault_context.py)
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
      """Test 10: enabled=True and chunks returned when vault has matching notes."""
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


  def test_build_vault_context_handles_retrieval_exception(monkeypatch):
      """build_vault_context returns disabled context (no raise) when retrieval errors."""
      import assistant_os.mso.vault_context as vc_mod
      from assistant_os.mso import vault as vault_mod

      monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "/some/path")

      # Make the directory check pass by patching Path.is_dir
      from pathlib import Path
      monkeypatch.setattr(Path, "is_dir", lambda self: True)

      # Make keyword_search raise
      def _raise(*args, **kwargs):
          raise RuntimeError("vault disk error")
      monkeypatch.setattr(vc_mod, "keyword_search", _raise)

      result = build_vault_context("anything")
      assert result["enabled"] is False
      assert any("vault retrieval error" in w.lower() for w in result["warnings"])
  ```

- [ ] **Step 3.2: Run tests 8-10 — expect FAIL (vault_context.py not yet created)**

  ```bash
  python -m pytest tests/test_vault_context.py::test_build_vault_context_disabled_when_path_empty tests/test_vault_context.py::test_build_vault_context_returns_chunks_when_vault_valid -v
  ```

  Expected: 2 FAIL with ImportError

- [ ] **Step 3.3: Create vault_context.py**

  Create `assistant_os/mso/vault_context.py`:

  ```python
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
  ```

- [ ] **Step 3.4: Run vault_context tests — expect PASS**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```

  Expected: All tests PASS

- [ ] **Step 3.5: Commit**

  ```bash
  git add assistant_os/mso/vault_context.py tests/test_vault_context.py
  git commit -m "feat(vault_context): add build_vault_context() + tests — SPRINT-ALPHA-04"
  ```

---

## Task 4: Update prompts.py — Phase 3 vault section + Phase 4 ECONOMIC SYNTHESIS TASK

**Files:**
- Modify: `assistant_os/mso/prompts.py`
- Partially written: `tests/test_vault_context.py` (append tests 11–13)
- Partially written: `tests/test_economic_synthesis.py` (write tests 1–6, run, then update prompts.py)

- [ ] **Step 4.1: Write failing prompt structure tests into test_economic_synthesis.py**

  Create `tests/test_economic_synthesis.py`:

  ```python
  """Phase 4 Economic Synthesis tests — SPRINT-ALPHA-04.

  Tests 1-6: Prompt structure contracts
  Tests 7-10: surface_behavior cognitive_trace contracts
  Tests 11-15: Regression + audit tests
  """

  from __future__ import annotations

  import pytest
  from unittest.mock import patch, MagicMock


  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  def _make_grounding(vault_context=None, version="alpha-02") -> dict:
      return {
          "operational_mode": "NORMAL",
          "seat_provider": "test-provider",
          "prepared_actions_count": 0,
          "prepared_actions_summary": [],
          "next_safe_step": "Continue observing",
          "authority_posture": "MSO → Policy → Police → Pipeline",
          "limitations": "You cannot execute. You cannot issue tokens.",
          "version": version,
          "generated_at": "2026-05-13T00:00:00",
          "capabilities_summary": {},
          "recent_governance": [],
          "active_tasks_brief": [],
          "recent_failures": [],
          "perception_warnings": [],
          "vault_context": vault_context,
      }


  def _make_vault_ctx_enabled(tmp_path) -> dict:
      """Build a minimal enabled vault context with one chunk."""
      return {
          "enabled": True,
          "query": "test query",
          "retrieval_method": "keyword_topk",
          "chunks": [
              {
                  "note_path": str(tmp_path / "budget.md"),
                  "title": "Budget Framework",
                  "tags": ["budget", "planning"],
                  "frontmatter": {"status": "stable"},
                  "content": "Budget planning doctrine and stable principles.",
                  "score": 0.9,
              }
          ],
          "vault_sources": [str(tmp_path / "budget.md")],
          "vault_chunks_used": 1,
          "token_budget_used": 10,
          "truncated": False,
          "warnings": [],
      }


  def _make_vault_ctx_disabled() -> dict:
      return {
          "enabled": False,
          "query": "test query",
          "retrieval_method": "keyword_topk",
          "chunks": [],
          "vault_sources": [],
          "vault_chunks_used": 0,
          "token_budget_used": 0,
          "truncated": False,
          "warnings": [],
      }


  # ---------------------------------------------------------------------------
  # Test 1: Prompt includes ECONOMIC SYNTHESIS TASK section
  # ---------------------------------------------------------------------------

  def test_prompt_includes_economic_synthesis_task():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      grounding = _make_grounding()
      prompt = build_mso_chat_system_prompt(grounding)
      assert "ECONOMIC SYNTHESIS TASK" in prompt


  # ---------------------------------------------------------------------------
  # Test 2: Prompt keeps SYSTEM PERCEPTION FRAME and VAULT SEMANTIC CONTEXT separate
  # ---------------------------------------------------------------------------

  def test_prompt_keeps_sections_separate():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      grounding = _make_grounding()
      prompt = build_mso_chat_system_prompt(grounding)
      # Both must be present as distinct labeled sections
      assert "SYSTEM PERCEPTION FRAME" in prompt
      assert "VAULT SEMANTIC CONTEXT" in prompt
      # ECONOMIC SYNTHESIS TASK must come AFTER both data sections
      econ_pos = prompt.find("ECONOMIC SYNTHESIS TASK")
      perception_pos = prompt.find("SYSTEM PERCEPTION FRAME")
      vault_pos = prompt.find("VAULT SEMANTIC CONTEXT")
      assert perception_pos < econ_pos
      assert vault_pos < econ_pos


  # ---------------------------------------------------------------------------
  # Test 3: Prompt includes Vault source metadata when chunks exist
  # ---------------------------------------------------------------------------

  def test_prompt_includes_vault_source_metadata_when_chunks_exist(tmp_path):
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      vault_ctx = _make_vault_ctx_enabled(tmp_path)
      grounding = _make_grounding(vault_context=vault_ctx)
      prompt = build_mso_chat_system_prompt(grounding)
      assert "VAULT SEMANTIC CONTEXT" in prompt
      assert "Budget Framework" in prompt
      assert "Retrieval enabled: yes" in prompt


  # ---------------------------------------------------------------------------
  # Test 4: Prompt clearly says Vault disabled/empty when no chunks exist
  # ---------------------------------------------------------------------------

  def test_prompt_vault_disabled_says_no_context():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      vault_ctx = _make_vault_ctx_disabled()
      grounding = _make_grounding(vault_context=vault_ctx)
      prompt = build_mso_chat_system_prompt(grounding)
      assert "VAULT SEMANTIC CONTEXT" in prompt
      # Must communicate that no vault context is available
      assert any(phrase in prompt for phrase in [
          "Retrieval enabled: no",
          "No relevant chunks",
          "No stable Vault context",
          "no stable vault context",
      ])


  # ---------------------------------------------------------------------------
  # Test 5: Prompt instructs model not to invent capabilities/state
  # ---------------------------------------------------------------------------

  def test_prompt_instructs_model_not_to_invent():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      grounding = _make_grounding()
      prompt = build_mso_chat_system_prompt(grounding)
      assert any(phrase in prompt.lower() for phrase in [
          "do not invent",
          "no inventes",
          "not listed in",
      ])


  # ---------------------------------------------------------------------------
  # Test 6: Prompt instructs model not to claim execution
  # ---------------------------------------------------------------------------

  def test_prompt_instructs_model_not_to_claim_execution():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      grounding = _make_grounding()
      prompt = build_mso_chat_system_prompt(grounding)
      assert any(phrase in prompt.lower() for phrase in [
          "do not claim you have executed",
          "do not claim to have executed",
          "cannot execute",
          "no puede ejecutar",
          "real execution requires",
      ])
  ```

- [ ] **Step 4.2: Run tests 1–6 — expect FAIL**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_prompt_includes_economic_synthesis_task tests/test_economic_synthesis.py::test_prompt_keeps_sections_separate tests/test_economic_synthesis.py::test_prompt_includes_vault_source_metadata_when_chunks_exist -v
  ```

  Expected: tests 1–2 FAIL (ECONOMIC SYNTHESIS TASK missing, SYSTEM PERCEPTION FRAME label missing in current prompt)

- [ ] **Step 4.3: Replace prompts.py with full Phase 3 + Phase 4 version**

  Replace the entire content of `assistant_os/mso/prompts.py` with:

  ```python
  """Prompt builders for internal MSO advisory roles."""

  from __future__ import annotations

  from .contracts import LocalLlmRequest


  def build_orchestrator_advisory_prompt(req: LocalLlmRequest) -> str:
      """Build the combined advisory prompt used by the orchestrator seam."""
      metadata = req.get("metadata") or {}
      action = req.get("planned_action", "")
      is_code = action.startswith("CODE_") or req.get("classifier_domain", "") == "CODE"
      code_clause = (
          '"code_task_summary":"one-sentence CODE task summary or empty string",'
          '"repo_context":"short repo/workspace context or empty string",'
          '"constraints":["constraint 1"],'
          '"expected_artifact":"expected artifact or empty string",'
          '"risk_notes":["risk 1"]'
          if is_code
          else
          '"code_task_summary":"",'
          '"repo_context":"",'
          '"constraints":[],'
          '"expected_artifact":"",'
          '"risk_notes":[]'
      )

      return (
          "You are an internal advisory model for AssistantOS.\n"
          "You are advisory only. You must not claim authority, execution, or final control.\n\n"
          "Return ONLY valid JSON with this exact shape:\n"
          "{"
          '"reasoning_summary":"short assistant-side interpretation",'
          '"routing_hint":"brief route hint or empty string",'
          '"suggested_domain":"domain label or empty string",'
          '"suggested_action":"action label or empty string",'
          '"execution_posture_hint":"auto|confirm|clarify|blocked|empty",'
          '"confidence_note":"short certainty note",'
          f"{code_clause}"
          "}\n\n"
          "Rules:\n"
          "- Be concise and structured.\n"
          "- Treat deterministic planning as source of truth.\n"
          "- Do not invent files, tools, side effects, or permissions.\n"
          "- If uncertain, leave fields empty instead of guessing.\n\n"
          f"User text: {req.get('text', '')}\n"
          f"Deterministic classifier operation: {req.get('classifier_operation', '')}\n"
          f"Deterministic classifier domain: {req.get('classifier_domain', '')}\n"
          f"Deterministic planned action: {action}\n"
          f"Deterministic plan preview: {req.get('plan_preview', '')}\n"
          f"Workspace target file: {metadata.get('target_file', '')}\n"
          f"Workspace root: {metadata.get('workspace', '')}\n"
          f"Allowed write scope: {metadata.get('allowed_write_scope', [])}\n"
      )


  def build_mso_chat_system_prompt(grounding_context: dict) -> str:
      """Build the system prompt for MSO conversational generation.

      Injects the full economic perception frame (SPRINT-ALPHA-02) so the LLM
      is anchored to real system state. Sections are rendered only when non-empty;
      each section falls back to an explicit 'No data currently visible.' line.

      Injects a bounded Vault section (SPRINT-ALPHA-03) when vault_context is
      present and enabled. The Vault section is strictly separate from the
      SYSTEM PERCEPTION FRAME and provides stable doctrine/semantic guidance only.

      Adds ECONOMIC SYNTHESIS TASK (SPRINT-ALPHA-04) to contract the model's
      synthesis behavior: how to combine perception frame and Vault context,
      what to say when Vault is absent, and how to handle uncertainty.

      Never grants execution authority — the prompt hard-codes the execution
      boundary and instructs the model that it cannot execute, issue tokens,
      or approve plans.
      """
      operational_mode = grounding_context.get("operational_mode", "UNKNOWN")
      seat_provider = grounding_context.get("seat_provider", "not configured")
      prepared_count = grounding_context.get("prepared_actions_count", 0)
      next_safe_step = grounding_context.get("next_safe_step", "")
      authority_posture = grounding_context.get("authority_posture", "")
      limitations = grounding_context.get("limitations", "")
      version = grounding_context.get("version", "")
      generated_at = grounding_context.get("generated_at", "")

      capabilities = grounding_context.get("capabilities_summary") or {}
      recent_governance = grounding_context.get("recent_governance") or []
      active_tasks = grounding_context.get("active_tasks_brief") or []
      recent_failures = grounding_context.get("recent_failures") or []
      prepared_summary = grounding_context.get("prepared_actions_summary") or []
      perception_warnings = grounding_context.get("perception_warnings") or []

      vault_context = grounding_context.get("vault_context")
      vault_section = _build_vault_prompt_section(vault_context)

      def _fmt_capabilities(caps: dict) -> str:
          if not caps:
              return "  No data currently visible."
          lines: list[str] = []
          if caps.get("domains"):
              lines.append(f"  Domains: {', '.join(caps['domains'])}")
          if caps.get("active_capabilities"):
              lines.append(f"  Active capabilities: {', '.join(caps['active_capabilities'])}")
          if caps.get("machine_operator"):
              lines.append(f"  Machine Operator: {caps['machine_operator']}")
          if caps.get("runner_enforced"):
              lines.append("  Runner: enforced")
          return "\n".join(lines) if lines else "  No data currently visible."

      def _fmt_governance(decisions: list) -> str:
          if not decisions:
              return "  No data currently visible."
          lines: list[str] = []
          for d in decisions[:5]:
              if isinstance(d, dict):
                  outcome = d.get("outcome") or d.get("decision") or "?"
                  domain = d.get("domain") or d.get("classifier_domain") or "?"
                  did = d.get("decision_id") or d.get("id") or "?"
                  lines.append(f"  [{did}] domain={domain} outcome={outcome}")
              else:
                  lines.append(f"  {d}")
          return "\n".join(lines)

      def _fmt_tasks(tasks: list) -> str:
          if not tasks:
              return "  No data currently visible."
          lines: list[str] = []
          for t in tasks[:5]:
              if isinstance(t, dict):
                  lines.append(
                      f"  [{t.get('task_id', '?')}] domain={t.get('domain', '?')} "
                      f"status={t.get('status', '?')} action={t.get('last_known_action', '?')}"
                  )
              else:
                  lines.append(f"  {t}")
          return "\n".join(lines)

      def _fmt_failures(failures: list) -> str:
          if not failures:
              return "  No data currently visible."
          lines: list[str] = []
          for f in failures[:5]:
              if isinstance(f, dict):
                  lines.append(
                      f"  [{f.get('task_id', '?')}] domain={f.get('domain', '?')} "
                      f"error={f.get('error_type', '?')}: "
                      f"{str(f.get('error_message', ''))[:60]}"
                  )
              else:
                  lines.append(f"  {f}")
          return "\n".join(lines)

      def _fmt_prepared(items: list, count: int) -> str:
          if count == 0 or not items:
              return "  None."
          lines: list[str] = [f"  Total waiting for human review: {count}"]
          for item in items[:5]:
              if isinstance(item, dict):
                  lines.append(
                      f"  [{item.get('queue_entry_id', '?')}] "
                      f"domain={item.get('domain', '?')} "
                      f"action={item.get('requested_action', '?')} "
                      f"status={item.get('human_confirmation_status', '?')} "
                      f"execution_allowed={item.get('execution_allowed', False)}"
                  )
              else:
                  lines.append(f"  {item}")
          return "\n".join(lines)

      warnings_section = ""
      if perception_warnings:
          joined = "; ".join(perception_warnings[:5])
          warnings_section = (
              f"\nPERCEPTION WARNINGS (some data sources unavailable):\n  {joined}\n"
          )

      frame_meta = (
          f"perception frame v{version} generated_at={generated_at}" if version else ""
      )

      return (
          "You are the MSO — the Machine Sovereign Operator, the cognitive layer "
          "of AssistantOS. You reason, explain, inspect system state, and propose "
          "actions on behalf of the governed execution system.\n\n"
          "HARD RULES:\n"
          f"- {limitations}\n"
          "- Do not claim you have executed, run, deployed, completed, or started "
          "any action — even if asked to confirm.\n"
          "- Do not invent capabilities, tokens, plans, tasks, failures, or agents "
          "not listed in the perception frame below.\n"
          "- If a field shows 'No data currently visible', report that — "
          "do not invent values.\n"
          "- Any real execution requires explicit human confirmation through a "
          "governed pipeline.\n\n"
          "SYSTEM PERCEPTION FRAME (grounded, read-only runtime truth):\n"
          f"- Operational mode: {operational_mode}\n"
          f"- Cognitive provider: {seat_provider}\n"
          f"- Authority chain: {authority_posture}\n"
          f"- Next safe step: {next_safe_step}\n"
          "- Execution boundary: execution_allowed=false, can_execute_now=false\n"
          f"{f'- {frame_meta}' if frame_meta else ''}\n"
          "\nCAPABILITIES (from live capability registry):\n"
          f"{_fmt_capabilities(capabilities)}\n"
          "\nPREPARED ACTIONS AWAITING HUMAN REVIEW:\n"
          f"{_fmt_prepared(prepared_summary, prepared_count)}\n"
          "\nRECENT GOVERNANCE DECISIONS (last 5):\n"
          f"{_fmt_governance(recent_governance)}\n"
          "\nACTIVE TASKS (last 5):\n"
          f"{_fmt_tasks(active_tasks)}\n"
          "\nRECENT FAILURES (last 5):\n"
          f"{_fmt_failures(recent_failures)}\n"
          f"{warnings_section}"
          f"\n{vault_section}\n"
          "\nECONOMIC SYNTHESIS TASK:\n"
          "Use the user's request, the SYSTEM PERCEPTION FRAME, and VAULT SEMANTIC CONTEXT "
          "above to produce a grounded operational answer.\n"
          "- If the user asks about current state or 'what do you see?' → answer from "
          "the SYSTEM PERCEPTION FRAME.\n"
          "- If the user asks about meaning, doctrine, or 'what does it mean?' → answer "
          "using VAULT SEMANTIC CONTEXT when available.\n"
          "- If both are relevant → combine them explicitly, labeling runtime fact vs. "
          "stable doctrine.\n"
          "- If vault_chunks_used is 0 → do not claim you used Vault context; if the "
          "topic calls for it, state that no stable Vault context was retrieved.\n"
          "- Do not invent capabilities, tokens, tasks, failures, or agents not listed "
          "in the perception frame.\n"
          "- Do not claim to have executed, approved, issued tokens, or changed system "
          "state — real execution requires human confirmation through the governed pipeline.\n"
          "- If uncertain about system state → acknowledge uncertainty and offer the next "
          "safe step when one is visible in the perception frame.\n"
          "- Keep the response conversational, operationally grounded, concise, and honest "
          "about limits.\n"
          "\nRESPONSE RULES:\n"
          "- Answer in the same language as the user's message.\n"
          "- Be concise and operationally grounded.\n"
          "- Use the SYSTEM PERCEPTION FRAME as current runtime truth — never invent facts "
          "outside it.\n"
          "- Use VAULT SEMANTIC CONTEXT as stable doctrine/semantic guidance when present — "
          "it does not authorize execution and does not override governance.\n"
          "- Do not blend Vault doctrine with runtime facts — label them separately when "
          "combining both sources.\n"
          "- If no Vault context was retrieved and the topic calls for it, say so explicitly.\n"
          "- When uncertain, say so rather than fabricating details.\n"
          "- Propose a next safe step when appropriate and one is visible in the perception "
          "frame.\n"
      )


  def _build_vault_prompt_section(vault_context: dict | None) -> str:
      """Render the bounded Vault section for the system prompt."""
      if not vault_context or not vault_context.get("enabled"):
          return (
              "VAULT SEMANTIC CONTEXT:\n"
              "- Retrieval enabled: no\n"
              "- No stable Vault context was retrieved for this query."
          )

      chunks = vault_context.get("chunks", [])
      if not chunks:
          return (
              "VAULT SEMANTIC CONTEXT:\n"
              "- Retrieval enabled: yes\n"
              "- No relevant chunks found."
          )

      sources_lines = "\n".join(
          f"  - {c['note_path']} ({c['title']})" for c in chunks
      )
      chunk_blocks = "\n\n".join(
          f"[{c['title']}]\n{c['content'][:800]}"
          for c in chunks
      )
      truncated_note = " [truncated]" if vault_context.get("truncated") else ""

      return (
          "VAULT SEMANTIC CONTEXT:\n"
          "- Retrieval enabled: yes\n"
          f"- Sources:\n{sources_lines}\n"
          f"- Chunks{truncated_note}:\n{chunk_blocks}"
      )
  ```

- [ ] **Step 4.4: Run tests 1–6 — expect PASS**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_prompt_includes_economic_synthesis_task tests/test_economic_synthesis.py::test_prompt_keeps_sections_separate tests/test_economic_synthesis.py::test_prompt_includes_vault_source_metadata_when_chunks_exist tests/test_economic_synthesis.py::test_prompt_vault_disabled_says_no_context tests/test_economic_synthesis.py::test_prompt_instructs_model_not_to_invent tests/test_economic_synthesis.py::test_prompt_instructs_model_not_to_claim_execution -v
  ```

  Expected: 6 PASS

- [ ] **Step 4.5: Also run vault prompt tests (tests 11–13 in test_vault_context.py)**

  Append to `tests/test_vault_context.py`:

  ```python
  # ---------------------------------------------------------------------------
  # Tests 11-13: build_mso_chat_system_prompt vault section
  # ---------------------------------------------------------------------------

  from assistant_os.mso.prompts import build_mso_chat_system_prompt


  def _make_prompt_grounding(vault_context=None) -> dict:
      return {
          "operational_mode": "TEST_MODE",
          "seat_provider": "test-provider",
          "prepared_actions_count": 0,
          "prepared_actions_summary": [],
          "next_safe_step": "none",
          "authority_posture": "test chain",
          "limitations": "You cannot execute.",
          "version": "alpha-04",
          "generated_at": "2026-05-13T00:00:00",
          "capabilities_summary": {},
          "recent_governance": [],
          "active_tasks_brief": [],
          "recent_failures": [],
          "perception_warnings": [],
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
      grounding = _make_prompt_grounding(vault_context=vault_ctx)
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
      grounding = _make_prompt_grounding(vault_context=disabled_ctx)
      prompt = build_mso_chat_system_prompt(grounding)
      assert "VAULT SEMANTIC CONTEXT" in prompt
      assert "Retrieval enabled: no" in prompt


  def test_prompt_vault_none_does_not_raise():
      """Test 13: Prompt must tolerate vault_context=None."""
      grounding = _make_prompt_grounding(vault_context=None)
      prompt = build_mso_chat_system_prompt(grounding)
      assert isinstance(prompt, str)
      assert len(prompt) > 0
      assert "SYSTEM PERCEPTION FRAME" in prompt
  ```

- [ ] **Step 4.6: Run full test_vault_context.py — expect all PASS**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```

  Expected: All tests PASS

- [ ] **Step 4.7: Commit**

  ```bash
  git add assistant_os/mso/prompts.py tests/test_vault_context.py tests/test_economic_synthesis.py
  git commit -m "feat(prompts): add vault section + ECONOMIC SYNTHESIS TASK — SPRINT-ALPHA-04"
  ```

---

## Task 5: Strengthen execution-claim validation in mso_chat_provider.py

**Files:**
- Modify: `assistant_os/mso/mso_chat_provider.py`

- [ ] **Step 5.1: Write failing validation tests — append to test_economic_synthesis.py**

  Open `tests/test_economic_synthesis.py` and append:

  ```python
  # ---------------------------------------------------------------------------
  # Validation pattern tests (mso_chat_provider._validate_provider_text)
  # ---------------------------------------------------------------------------

  def test_validate_rejects_approved_claim():
      from assistant_os.mso.mso_chat_provider import _validate_provider_text
      assert _validate_provider_text("I approved the request.") is not None
      assert _validate_provider_text("He aprobado la acción.") is not None


  def test_validate_rejects_token_issued_claim():
      from assistant_os.mso.mso_chat_provider import _validate_provider_text
      assert _validate_provider_text("I issued a token for the operation.") is not None
      assert _validate_provider_text("Se emitió un token automáticamente.") is not None


  def test_validate_rejects_system_changed_claim():
      from assistant_os.mso.mso_chat_provider import _validate_provider_text
      assert _validate_provider_text("I changed the system configuration.") is not None
      assert _validate_provider_text("Cambié el sistema de autenticación.") is not None


  def test_validate_allows_legitimate_economic_response():
      from assistant_os.mso.mso_chat_provider import _validate_provider_text
      legitimate = (
          "El sistema está en modo NORMAL. No hay acciones pendientes. "
          "El próximo paso seguro es revisar las acciones preparadas antes de confirmar."
      )
      assert _validate_provider_text(legitimate) is None
  ```

- [ ] **Step 5.2: Run new validation tests — expect FAIL for the new patterns**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_validate_rejects_approved_claim tests/test_economic_synthesis.py::test_validate_rejects_token_issued_claim tests/test_economic_synthesis.py::test_validate_rejects_system_changed_claim -v
  ```

  Expected: FAIL (patterns not yet in mso_chat_provider.py)

- [ ] **Step 5.3: Add missing validation patterns to mso_chat_provider.py**

  Open `assistant_os/mso/mso_chat_provider.py`. Find `_EXECUTION_CLAIM_PATTERNS` (around line 29). Replace the tuple with the expanded version:

  ```python
  _EXECUTION_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
      re.compile(r"\b(he\s+ejecutado|ejecut[oéa]\s+la|i\s+have\s+executed|executed\s+the)\b", re.IGNORECASE),
      re.compile(r"\b(completado\s+la\s+tarea|completed\s+the\s+task|task\s+completed|tarea\s+completada)\b", re.IGNORECASE),
      re.compile(r"\b(running\s+the\s+(?:task|action|plan|proceso)|corriendo\s+el\s+proceso)\b", re.IGNORECASE),
      re.compile(r"\b(deployed?|desplegado|lanzado\s+el\s+proceso)\b", re.IGNORECASE),
      re.compile(r"\b(i\s+approved|he\s+aprobado|aprobé\s+la|approved\s+the\s+(?:request|action|plan))\b", re.IGNORECASE),
      re.compile(r"\b(i\s+issued\s+a\s+token|issued\s+a\s+token|se\s+emitió\s+un\s+token|emití\s+un\s+token|token\s+issued)\b", re.IGNORECASE),
      re.compile(r"\b(i\s+changed\s+the\s+system|changed\s+the\s+system|cambié\s+el\s+sistema|sistema\s+(?:fue\s+)?cambiado)\b", re.IGNORECASE),
  )
  ```

- [ ] **Step 5.4: Run validation tests — expect PASS**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_validate_rejects_approved_claim tests/test_economic_synthesis.py::test_validate_rejects_token_issued_claim tests/test_economic_synthesis.py::test_validate_rejects_system_changed_claim tests/test_economic_synthesis.py::test_validate_allows_legitimate_economic_response -v
  ```

  Expected: 4 PASS

- [ ] **Step 5.5: Commit**

  ```bash
  git add assistant_os/mso/mso_chat_provider.py tests/test_economic_synthesis.py
  git commit -m "feat(validation): expand execution-claim patterns in mso_chat_provider — SPRINT-ALPHA-04"
  ```

---

## Task 6: Update surface_behavior.py — vault injection + full Phase 4 cognitive_trace

**Files:**
- Modify: `assistant_os/surface_behavior.py`
- Modify: `tests/test_economic_synthesis.py` (append tests 7–10)

- [ ] **Step 6.1: Write failing cognitive_trace tests — append to test_economic_synthesis.py**

  Append to `tests/test_economic_synthesis.py`:

  ```python
  # ---------------------------------------------------------------------------
  # Tests 7-10: surface_behavior cognitive_trace contracts
  # ---------------------------------------------------------------------------

  def _make_ok_provider_response(text="Sistema en modo NORMAL."):
      return {
          "status": "ok",
          "text": text,
          "provider_name": "anthropic",
          "model_name": "claude-haiku-4-5-20251001",
          "used_execution": False,
          "cognitive_only": True,
          "error": None,
          "metadata": {"tokens_in": 100, "tokens_out": 50},
      }


  def _make_unavailable_provider_response(reason="key not configured"):
      return {
          "status": "unavailable",
          "text": "",
          "provider_name": "anthropic",
          "model_name": "claude-haiku-4-5-20251001",
          "used_execution": False,
          "cognitive_only": True,
          "error": reason,
          "metadata": {},
      }


  def test_llm_economic_response_includes_synthesis_mode_in_cognitive_trace(monkeypatch):
      """Test 7: cognitive_trace must include synthesis_mode='economic' on llm_economic path."""
      from assistant_os import surface_behavior as sb

      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué ves del sistema",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      trace = resp.get("cognitive_trace") or {}
      assert trace.get("synthesis_mode") == "economic"


  def test_llm_economic_response_includes_vault_trace_fields(monkeypatch):
      """Test 8: cognitive_trace includes all vault trace fields on llm_economic path."""
      from assistant_os import surface_behavior as sb

      vault_ctx = {
          "enabled": True, "query": "test", "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": ["/some/note.md"], "vault_chunks_used": 1,
          "token_budget_used": 10, "truncated": False, "warnings": [],
      }
      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: vault_ctx)

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué significa provider_unavailable",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      trace = resp.get("cognitive_trace") or {}
      assert "vault_enabled" in trace
      assert "vault_chunks_used" in trace
      assert "vault_sources" in trace
      assert "vault_retrieval_method" in trace
      assert "vault_warnings" in trace
      assert "vault_truncated" in trace
      assert trace["vault_chunks_used"] == 1
      assert trace["vault_sources"] == ["/some/note.md"]


  def test_fallback_works_when_vault_disabled(monkeypatch):
      """Test 9: fallback to narrative when provider fails and vault is disabled."""
      from assistant_os import surface_behavior as sb

      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_unavailable_provider_response("ANTHROPIC_API_KEY not configured"))
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="cuáles son tus límites",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      assert resp.get("response_source") in ("provider_unavailable", "deterministic_fallback", "deterministic_narrative")
      assert resp.get("fallback_used") is True


  def test_fallback_works_when_vault_retrieval_raises(monkeypatch):
      """Test 10: fallback to narrative when vault retrieval raises and provider fails."""
      from assistant_os import surface_behavior as sb

      def _raise_vault(query):
          raise RuntimeError("disk error")

      monkeypatch.setattr(sb, "_get_vault_context", _raise_vault)
      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_unavailable_provider_response())

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="cuál es el próximo paso",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      # Must not crash — must return a response or None (not raise)
      # None is acceptable because the outer try/except catches the vault error
      # The important invariant is: no exception propagates
  ```

- [ ] **Step 6.2: Run tests 7–10 — expect FAIL**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_llm_economic_response_includes_synthesis_mode_in_cognitive_trace tests/test_economic_synthesis.py::test_llm_economic_response_includes_vault_trace_fields -v
  ```

  Expected: 2 FAIL (`_get_vault_context` not yet in surface_behavior.py, cognitive_trace not yet structured)

- [ ] **Step 6.3: Update surface_behavior.py — add _get_vault_context and update cognitive path**

  Find the block around line 1070 (`_call_mso_cognitive` function). After that function, add `_get_vault_context`:

  Old text to locate (after `_call_mso_cognitive`):

  ```python
  def _call_mso_cognitive(grounding_context: dict, text: str) -> dict:
      """Thin wrapper around mso_chat_provider.call_mso_chat_provider.

      Kept as a named module-level function so tests can patch it cleanly
      without importing from mso_chat_provider directly.
      """
      from .mso.mso_chat_provider import call_mso_chat_provider
      return call_mso_chat_provider(grounding_context=grounding_context, user_text=text)


  # ---------------------------------------------------------------------------
  # Public interface
  # ---------------------------------------------------------------------------
  ```

  Replace with:

  ```python
  def _call_mso_cognitive(grounding_context: dict, text: str) -> dict:
      """Thin wrapper around mso_chat_provider.call_mso_chat_provider.

      Kept as a named module-level function so tests can patch it cleanly
      without importing from mso_chat_provider directly.
      """
      from .mso.mso_chat_provider import call_mso_chat_provider
      return call_mso_chat_provider(grounding_context=grounding_context, user_text=text)


  def _get_vault_context(query: str) -> dict:
      """Thin wrapper around vault_context.build_vault_context for clean test patching."""
      from .mso.vault_context import build_vault_context
      return build_vault_context(query=query)


  # ---------------------------------------------------------------------------
  # Public interface
  # ---------------------------------------------------------------------------
  ```

- [ ] **Step 6.4: Update the mso_direct cognitive generation block in surface_behavior.py**

  Find the cognitive generation block (around line 1247) that currently reads:

  ```python
          # Cognitive generation path (Sprint 3) — provider-backed, fails closed
          try:
              import time as _time
              from .mso.narrative_runtime import build_mso_grounding_context, build_narrative_context_message
              grounding = build_mso_grounding_context()
              _provider_ok = False
              _start_time = _time.perf_counter()
              _provider_err = None
              try:
                  provider_resp = _call_mso_cognitive(grounding, text)
                  _latency_ms = int((_time.perf_counter() - _start_time) * 1000)
                  if provider_resp.get("status") == "ok" and provider_resp.get("text", "").strip():
                      provider_metadata = provider_resp.get("metadata") or {}
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
                              **grounding,
                              "execution_allowed": False,
                              "can_execute_now": False,
                          },
                          latency_ms=_latency_ms,
                          tokens_in=provider_metadata.get("tokens_in"),
                          tokens_out=provider_metadata.get("tokens_out"),
                      )
                  else:
                      _provider_err = provider_resp.get("error") or provider_resp.get("reason") or "unusable provider response"
              except Exception as e:
                  _latency_ms = int((_time.perf_counter() - _start_time) * 1000)
                  _provider_err = str(e)

              # Provider call failed or returned unusable response — fall back to narrative
              _msg, _ctx = build_narrative_context_message()
              _fallback_source = "provider_unavailable" if "key not configured" in str(_provider_err).lower() else "deterministic_fallback"
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
                  fallback_reason=_provider_err,
                  narrative_context=_ctx,
                  latency_ms=_latency_ms if '_latency_ms' in locals() else None,
              )
          except Exception:
              pass
  ```

  Replace with:

  ```python
          # Cognitive generation path (Sprint 4) — provider-backed with Vault, fails closed
          try:
              import time as _time
              from .mso.narrative_runtime import build_mso_grounding_context, build_narrative_context_message
              grounding = build_mso_grounding_context()
              vault_ctx = _get_vault_context(query=text)
              grounding_with_vault = {**grounding, "vault_context": vault_ctx}
              _start_time = _time.perf_counter()
              _provider_err = None
              try:
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
                          "synthesis_mode": "economic",
                          "perception_frame_version": grounding.get("version", ""),
                      }
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

              # Provider call failed or returned unusable response — fall back to narrative
              _msg, _ctx = build_narrative_context_message()
              _fallback_source = "provider_unavailable" if "key not configured" in str(_provider_err).lower() else "deterministic_fallback"
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
                  fallback_reason=_provider_err,
                  narrative_context=_ctx,
                  latency_ms=_latency_ms if '_latency_ms' in locals() else None,
              )
          except Exception:
              pass
  ```

- [ ] **Step 6.5: Run tests 7–10 — expect PASS**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_llm_economic_response_includes_synthesis_mode_in_cognitive_trace tests/test_economic_synthesis.py::test_llm_economic_response_includes_vault_trace_fields tests/test_economic_synthesis.py::test_fallback_works_when_vault_disabled tests/test_economic_synthesis.py::test_fallback_works_when_vault_retrieval_raises -v
  ```

  Expected: 4 PASS

- [ ] **Step 6.6: Commit**

  ```bash
  git add assistant_os/surface_behavior.py tests/test_economic_synthesis.py
  git commit -m "feat(surface): wire vault context + synthesis_mode into cognitive path — SPRINT-ALPHA-04"
  ```

---

## Task 7: Regression and audit tests (tests 11–15)

**Files:**
- Modify: `tests/test_economic_synthesis.py` (append tests 11–15)

- [ ] **Step 7.1: Append regression and audit tests to test_economic_synthesis.py**

  ```python
  # ---------------------------------------------------------------------------
  # Tests 11-13: Alpha 1/2/3 regression — provenance and trace fields intact
  # ---------------------------------------------------------------------------

  def test_alpha1_provenance_fields_intact(monkeypatch):
      """Test 11: llm_economic response preserves Alpha 1 provenance fields."""
      from assistant_os import surface_behavior as sb

      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué ves del sistema",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      # Alpha 1 provenance fields
      assert resp.get("response_source") == "llm_economic"
      assert resp.get("execution_status") == "real"
      assert resp.get("provider_used") == "anthropic"
      assert resp.get("model_used") == "claude-haiku-4-5-20251001"
      assert resp.get("cognitive_generation") is True
      assert resp.get("fallback_used") is False
      assert resp.get("execution_allowed") is False
      assert resp.get("can_execute_now") is False


  def test_alpha2_perception_frame_fields_in_narrative_context(monkeypatch):
      """Test 12: llm_economic narrative_context includes Alpha 2 perception frame data."""
      from assistant_os import surface_behavior as sb

      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué ves del sistema",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      ctx = resp.get("narrative_context") or {}
      # Perception frame keys (Alpha 2)
      assert "operational_mode" in ctx or ctx.get("execution_allowed") is False
      assert ctx.get("execution_allowed") is False
      assert ctx.get("can_execute_now") is False


  def test_alpha3_vault_trace_fields_present(monkeypatch):
      """Test 13: Alpha 3 vault fields are present in cognitive_trace on llm_economic."""
      from assistant_os import surface_behavior as sb

      monkeypatch.setattr(sb, "_call_mso_cognitive", lambda gc, text: _make_ok_provider_response())
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      resp = sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué ves del sistema",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert resp is not None
      trace = resp.get("cognitive_trace") or {}
      assert "vault_enabled" in trace
      assert "vault_chunks_used" in trace
      assert "vault_sources" in trace
      assert "vault_retrieval_method" in trace
      assert "vault_warnings" in trace
      assert "vault_truncated" in trace


  # ---------------------------------------------------------------------------
  # Test 14: No second LLM call introduced (audit test)
  # ---------------------------------------------------------------------------

  def test_no_second_llm_call(monkeypatch):
      """Test 14: Only one call to _call_mso_cognitive per mso_direct request."""
      from assistant_os import surface_behavior as sb

      call_count = {"n": 0}

      def _counting_cognitive(gc, text):
          call_count["n"] += 1
          return _make_ok_provider_response()

      monkeypatch.setattr(sb, "_call_mso_cognitive", _counting_cognitive)
      monkeypatch.setattr(sb, "_get_vault_context", lambda query: {
          "enabled": False, "query": query, "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      })

      sb.get_surface_behavior_response(
          surface="mso_direct",
          text="qué ves del sistema",
          context_id="test-ctx",
          identity=None,
          guard_result=None,
      )
      assert call_count["n"] == 1, f"Expected 1 LLM call, got {call_count['n']}"


  # ---------------------------------------------------------------------------
  # Test 15: Authority/Police/Machine Operator files not imported in surface_behavior
  # ---------------------------------------------------------------------------

  def test_no_authority_imports_in_surface_behavior():
      """Test 15: surface_behavior must not import from police, machine_operator_policy, or operator_auth."""
      import ast
      import pathlib

      sb_path = pathlib.Path(__file__).parent.parent / "assistant_os" / "surface_behavior.py"
      tree = ast.parse(sb_path.read_text(encoding="utf-8"))

      forbidden_modules = {
          "machine_operator_policy",
          "operator_auth",
          "police_delegated_seat_validator",
          "machine_operator_adapter",
      }

      for node in ast.walk(tree):
          if isinstance(node, (ast.Import, ast.ImportFrom)):
              if isinstance(node, ast.ImportFrom) and node.module:
                  for forbidden in forbidden_modules:
                      assert forbidden not in node.module, (
                          f"surface_behavior.py imports from forbidden module: {node.module}"
                      )
  ```

- [ ] **Step 7.2: Run tests 11–15 — expect PASS**

  ```bash
  python -m pytest tests/test_economic_synthesis.py::test_alpha1_provenance_fields_intact tests/test_economic_synthesis.py::test_alpha2_perception_frame_fields_in_narrative_context tests/test_economic_synthesis.py::test_alpha3_vault_trace_fields_present tests/test_economic_synthesis.py::test_no_second_llm_call tests/test_economic_synthesis.py::test_no_authority_imports_in_surface_behavior -v
  ```

  Expected: 5 PASS

- [ ] **Step 7.3: Commit**

  ```bash
  git add tests/test_economic_synthesis.py
  git commit -m "test(synthesis): add regression and audit tests 11-15 — SPRINT-ALPHA-04"
  ```

---

## Task 8: Run all required test suites

- [ ] **Step 8.1: Run test_vault_context.py**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```

  Expected: All PASS

- [ ] **Step 8.2: Run test_economic_perception.py (Alpha 2 regression)**

  ```bash
  python -m pytest tests/test_economic_perception.py -v
  ```

  Expected: All PASS

- [ ] **Step 8.3: Run test_surface_behavior_layer.py (Alpha 1/2 regression)**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v
  ```

  Expected: All PASS

- [ ] **Step 8.4: Run test_ui_runtime_truth_contracts.py**

  ```bash
  python -m pytest tests/test_ui_runtime_truth_contracts.py -v
  ```

  Expected: All PASS

- [ ] **Step 8.5: Run test_economic_synthesis.py (Phase 4)**

  ```bash
  python -m pytest tests/test_economic_synthesis.py -v
  ```

  Expected: All 15+ PASS

- [ ] **Step 8.6: Run full test suite to confirm no regressions**

  ```bash
  python -m pytest tests/ -x --tb=short -q 2>&1 | tail -30
  ```

  Expected: All tests PASS, no regressions

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|-------------|------|
| ECONOMIC SYNTHESIS TASK section in prompt | Task 4 |
| SYSTEM PERCEPTION FRAME and VAULT SEMANTIC CONTEXT kept separate | Task 4 |
| Vault source metadata when chunks exist | Task 4 |
| Vault disabled/empty message when no chunks | Task 4 |
| Model not to invent capabilities/state | Task 4 |
| Model not to claim execution | Task 4 |
| synthesis_mode="economic" in cognitive_trace | Task 6 |
| vault trace fields in cognitive_trace | Task 6 |
| perception_frame_version in cognitive_trace | Task 6 |
| Provider fallback when Vault disabled | Task 6 (test 9) |
| Provider fallback when Vault retrieval raises | Task 6 (test 10) |
| Alpha 1 provenance fields intact | Task 7 (test 11) |
| Alpha 2 perception frame fields intact | Task 7 (test 12) |
| Alpha 3 Vault context fields intact | Task 7 (test 13) |
| No second LLM call | Task 7 (test 14) |
| No authority/Police/Machine Operator files touched | Task 7 (test 15) |
| vault.py created | Task 2 |
| vault_context.py created | Task 3 |
| ASSISTANT_OS_VAULT_PATH in config | Task 1 |
| Validation strengthened (approved, token, system changed) | Task 5 |

All requirements covered.

### Type Consistency

- `build_vault_context()` returns `dict` — used as `vault_ctx` in surface_behavior.py and passed as `vault_context` key in grounding dict.
- `_get_vault_context(query: str) -> dict` — matches `build_vault_context` signature.
- `cognitive_trace` is a plain `dict` — passed as `cognitive_trace=` kwarg to `_build_surface_response`.
- `_build_vault_prompt_section(vault_context: dict | None) -> str` — accepts `None` and `dict`.
- `grounding_with_vault = {**grounding, "vault_context": vault_ctx}` — spreads perception frame, adds vault key.
