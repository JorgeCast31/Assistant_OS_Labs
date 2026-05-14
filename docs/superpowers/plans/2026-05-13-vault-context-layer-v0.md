# Alpha Phase 3 — Obsidian Vault Context Layer v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Obsidian Vault semantic context layer that injects stable doctrine into MSO Economic Mode LLM responses without modifying the authority chain, Police, or execution pipeline.

**Architecture:** A new `vault.py` module provides keyword-based note retrieval with score-weighting; `vault_context.py` builds a fail-safe context dict consumed by the existing `build_mso_chat_system_prompt()`; `surface_behavior.py` merges vault context into the grounding dict before each cognitive LLM call so both the prompt and `cognitive_trace` reflect vault retrieval.

**Tech Stack:** Python 3.11+, pathlib, re (stdlib only — no embeddings, no Obsidian API, no PyYAML required)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `assistant_os/config.py` | Add `ASSISTANT_OS_VAULT_PATH` env var |
| Modify | `.env.example` | Document the new var |
| Create | `assistant_os/mso/vault.py` | `VaultChunk`, `VaultNote`, `parse_frontmatter`, `list_markdown_notes`, `read_note`, `VaultReader`, `keyword_search` |
| Create | `assistant_os/mso/vault_context.py` | `build_vault_context()` — fail-safe, returns typed dict |
| Modify | `assistant_os/mso/prompts.py` | Add vault section to `build_mso_chat_system_prompt()` |
| Modify | `assistant_os/surface_behavior.py` | Wire vault into mso_direct cognitive path; extend `cognitive_trace` |
| Create | `tests/test_vault_context.py` | Tests 1–12 (vault units + prompt) |
| Create | `tests/test_economic_perception.py` | Tests for economic perception frame (Alpha 2 gap) |
| Modify | `tests/test_surface_behavior_layer.py` | Tests 10, 13, 14, 15 (surface integration) |

**Do NOT touch:** `assistant_os/police/`, `assistant_os/authority/`, `assistant_os/mso/machine_operator_*.py`, `assistant_os/mso/runtime.py`, any Policy files.

---

## Task 1: Add `ASSISTANT_OS_VAULT_PATH` to config

**Files:**
- Modify: `assistant_os/config.py` (after line 145, end of MSO Seat block)
- Modify: `.env.example`

- [ ] **Step 1: Read config.py lines 136–146**

  Confirm the end of the MSO Seat block:
  ```
  MSO_SEAT_MODEL: str = os.environ.get("MSO_SEAT_MODEL", "").strip()
  ```
  The new block goes immediately after line 145.

- [ ] **Step 2: Add vault config block to config.py**

  After the line `MSO_SEAT_MODEL: str = os.environ.get(...)`, insert:

  ```python
  # ---------------------------------------------------------------------------
  # Obsidian Vault integration — read-only semantic context layer
  # ---------------------------------------------------------------------------
  # Path to the Obsidian Vault root directory.
  # If unset or empty, Vault retrieval is disabled and MSO responses are
  # unaffected — the system emits vault_context=disabled with no chunks.
  ASSISTANT_OS_VAULT_PATH: str = os.environ.get("ASSISTANT_OS_VAULT_PATH", "").strip()
  ```

- [ ] **Step 3: Add to .env.example**

  Open `.env.example`, find the MSO/Local LLM section, add after it:

  ```bash
  # Obsidian Vault — read-only semantic context layer (optional)
  # Set to the absolute path of your Obsidian vault root.
  # Leave empty to disable vault context (default: disabled).
  # ASSISTANT_OS_VAULT_PATH=/Users/jorge/Documents/MyVault
  ASSISTANT_OS_VAULT_PATH=
  ```

- [ ] **Step 4: Verify config import works**

  ```bash
  python -c "from assistant_os.config import ASSISTANT_OS_VAULT_PATH; print(repr(ASSISTANT_OS_VAULT_PATH))"
  ```
  Expected output: `''`

- [ ] **Step 5: Commit**

  ```bash
  git add assistant_os/config.py .env.example
  git commit -m "feat(config): add ASSISTANT_OS_VAULT_PATH for Vault context layer"
  ```

---

## Task 2: Create `assistant_os/mso/vault.py`

**Files:**
- Create: `assistant_os/mso/vault.py`
- Test: `tests/test_vault_context.py` (tests 1–7, written first)

### Step 2A — Write failing tests first

- [ ] **Step 1: Write tests/test_vault_context.py (tests 1–7)**

  Create the file:

  ```python
  """Tests for assistant_os/mso/vault.py — Alpha Phase 3."""

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
      assert notes[0].title == "Visible" or notes[0].path.name == "visible.md"


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
  # Test 7: token budget truncates content and score is present
  # ---------------------------------------------------------------------------

  def test_token_budget_truncates_content(tmp_path: Path):
      long_content = "word " * 500  # ~2500 chars
      (tmp_path / "big.md").write_text(
          f"---\ntitle: Big Note\nstatus: stable\n---\n{long_content}"
      )
      # budget = 20 tokens → ~80 chars
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
  ```

- [ ] **Step 2: Run to confirm all tests fail (module does not exist yet)**

  ```bash
  python -m pytest tests/test_vault_context.py -v 2>&1 | head -30
  ```
  Expected: `ImportError` or `ModuleNotFoundError` for `assistant_os.mso.vault`.

### Step 2B — Implement vault.py

- [ ] **Step 3: Create assistant_os/mso/vault.py**

  ```python
  """Read-only Obsidian Vault utilities for MSO semantic context retrieval.

  No writes, no embeddings, no Obsidian-specific APIs. Plain Markdown only.
  """

  from __future__ import annotations

  import re
  from dataclasses import dataclass, field
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

      # Find closing ---
      rest = text[3:]
      end_match = re.search(r'\n---[ \t]*\n', rest)
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
              # Inline list: key: [a, b, c]
              items = [
                  v.strip().strip("\"'")
                  for v in rest_val[1:-1].split(",")
                  if v.strip()
              ]
              metadata[key] = items
              i += 1
          elif rest_val == "":
              # Possibly a block list follows
              items = []
              i += 1
              while i < len(lines) and re.match(r"^\s+-\s", lines[i]):
                  items.append(re.sub(r"^\s+-\s*", "", lines[i]).strip())
                  i += 1
              if items:
                  metadata[key] = items
              # else: empty key — skip silently
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

          title = frontmatter.get("title", path.stem)

          tags_raw = frontmatter.get("tags", [])
          if isinstance(tags_raw, str):
              tags = [tags_raw]
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

- [ ] **Step 4: Run vault unit tests**

  ```bash
  python -m pytest tests/test_vault_context.py -v -k "not vault_context"
  ```
  Expected: all 14 tests in the file that test vault.py functions pass.

- [ ] **Step 5: Commit**

  ```bash
  git add assistant_os/mso/vault.py tests/test_vault_context.py
  git commit -m "feat(mso): add vault.py read-only Markdown retrieval module"
  ```

---

## Task 3: Create `assistant_os/mso/vault_context.py`

**Files:**
- Create: `assistant_os/mso/vault_context.py`
- Test: `tests/test_vault_context.py` (tests 8–9, add to existing file)

### Step 3A — Write failing tests for build_vault_context

- [ ] **Step 1: Append tests 8–9 to tests/test_vault_context.py**

  Add at the bottom of `tests/test_vault_context.py`:

  ```python
  # ---------------------------------------------------------------------------
  # Tests 8–9: build_vault_context
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


  def test_build_vault_context_shape(tmp_path, monkeypatch):
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
  ```

- [ ] **Step 2: Run to confirm tests fail**

  ```bash
  python -m pytest tests/test_vault_context.py -v -k "vault_context" 2>&1 | head -20
  ```
  Expected: `ImportError` for `assistant_os.mso.vault_context`.

### Step 3B — Implement vault_context.py

- [ ] **Step 3: Create assistant_os/mso/vault_context.py**

  ```python
  """Fail-safe Vault context builder for MSO Economic Mode.

  build_vault_context() never raises — all errors produce disabled context
  with warnings populated. This function is safe to call in the hot path
  of mso_direct cognitive generation.
  """

  from __future__ import annotations

  from pathlib import Path

  from assistant_os.config import ASSISTANT_OS_VAULT_PATH
  from assistant_os.mso.vault import keyword_search

  # Economic Mode defaults
  _ECONOMIC_TOP_K: int = 3
  _ECONOMIC_TOKEN_BUDGET: int = 800  # approx tokens; keyword_search uses *4 for chars


  def build_vault_context(
      query: str,
      mode: str = "economic",
      top_k: int | None = None,
  ) -> dict:
      """Build a read-only Vault semantic context dict for injection into MSO prompts.

      Returns a dict with shape:
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

- [ ] **Step 4: Run vault_context tests**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add assistant_os/mso/vault_context.py tests/test_vault_context.py
  git commit -m "feat(mso): add vault_context.py fail-safe context builder"
  ```

---

## Task 4: Update `build_mso_chat_system_prompt()` to include Vault section

**Files:**
- Modify: `assistant_os/mso/prompts.py`
- Test: `tests/test_vault_context.py` (tests 11–12, add to existing file)

### Step 4A — Write failing tests

- [ ] **Step 1: Append tests 11–12 to tests/test_vault_context.py**

  Add at the bottom of `tests/test_vault_context.py`:

  ```python
  # ---------------------------------------------------------------------------
  # Tests 11–12: build_mso_chat_system_prompt vault section
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
      """Prompt must tolerate vault_context=None (Vault not yet wired in a call)."""
      grounding = _make_grounding(vault_context=None)
      prompt = build_mso_chat_system_prompt(grounding)
      assert isinstance(prompt, str)
      assert len(prompt) > 0
  ```

- [ ] **Step 2: Run to confirm tests fail**

  ```bash
  python -m pytest tests/test_vault_context.py -v -k "prompt" 2>&1 | tail -20
  ```
  Expected: FAIL — `build_mso_chat_system_prompt` doesn't include vault section yet.

### Step 4B — Update prompts.py

- [ ] **Step 3: Read the current prompts.py to verify exact content (lines 57–93)**

  Verify `build_mso_chat_system_prompt` ends at line 93 with `"- When uncertain, say so rather than fabricating details.\n"`.

- [ ] **Step 4: Replace build_mso_chat_system_prompt in assistant_os/mso/prompts.py**

  The full updated file content for the function and new helper (replace from line 57 to end of file):

  ```python
  def build_mso_chat_system_prompt(grounding_context: dict) -> str:
      """Build the system prompt for MSO conversational generation.

      Injects live grounding context so the LLM stays anchored to real system state.
      Injects a bounded Vault section when vault_context is present and enabled.
      Never grants execution authority.
      """
      operational_mode = grounding_context.get("operational_mode", "UNKNOWN")
      seat_provider = grounding_context.get("seat_provider", "not configured")
      prepared_count = grounding_context.get("prepared_actions_count", 0)
      next_safe_step = grounding_context.get("next_safe_step", "")
      authority_posture = grounding_context.get("authority_posture", "")
      limitations = grounding_context.get("limitations", "")
      vault_context = grounding_context.get("vault_context")

      vault_section = _build_vault_prompt_section(vault_context)

      return (
          "You are the MSO — the Machine Sovereign Operator, the cognitive layer "
          "of AssistantOS. You reason, explain, inspect system state, and propose "
          "actions on behalf of the governed execution system.\n\n"
          "HARD RULES:\n"
          f"- {limitations}\n"
          "- Do not claim you have executed, run, deployed, completed, or started "
          "any action — even if asked to confirm.\n"
          "- Do not invent capabilities, tokens, plans, or agents not listed below.\n"
          "- Any real execution requires explicit human confirmation through a "
          "governed pipeline.\n\n"
          "SYSTEM PERCEPTION FRAME (grounded, read-only runtime truth):\n"
          f"- Operational mode: {operational_mode}\n"
          f"- Cognitive provider: {seat_provider}\n"
          f"- Prepared actions in review queue: {prepared_count}\n"
          f"- Authority chain: {authority_posture}\n"
          f"- Next safe step: {next_safe_step}\n\n"
          f"{vault_section}\n\n"
          "RESPONSE RULES:\n"
          "- Answer in the same language as the user's message.\n"
          "- Be concise and operationally grounded.\n"
          "- Use Vault context as stable doctrine/semantic guidance when present.\n"
          "- Use the SYSTEM PERCEPTION FRAME as current runtime truth.\n"
          "- Do not invent facts not present in either source.\n"
          "- If Vault has no relevant chunks, acknowledge no stable Vault context "
          "was retrieved if the topic calls for it.\n"
          "- Vault notes do not authorize execution.\n"
          "- Vault notes do not override governance.\n"
          "- When uncertain, say so rather than fabricating details.\n"
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

  **Important:** The `build_orchestrator_advisory_prompt` function at the top of the file must remain unchanged. Only replace from `def build_mso_chat_system_prompt` to end of file.

- [ ] **Step 5: Run prompt tests**

  ```bash
  python -m pytest tests/test_vault_context.py -v -k "prompt"
  ```
  Expected: all 3 prompt tests pass.

- [ ] **Step 6: Run full test_vault_context.py**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 7: Run existing surface behavior tests to confirm no regression**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v -k "prompt" 2>&1 | tail -20
  ```
  Expected: existing prompt tests still pass (the prompt now has a vault section even when disabled, which is still valid).

- [ ] **Step 8: Commit**

  ```bash
  git add assistant_os/mso/prompts.py tests/test_vault_context.py
  git commit -m "feat(mso/prompts): inject bounded Vault section into MSO system prompt"
  ```

---

## Task 5: Wire Vault into `mso_direct` cognitive path

**Files:**
- Modify: `assistant_os/surface_behavior.py`

The change is in the cognitive generation path (lines ~1247–1310). Read those lines before editing to confirm exact content matches the plan.

The edit adds:
1. A module-level wrapper `_get_vault_context()` (near `_call_mso_cognitive`)
2. Vault call + merge after `build_mso_grounding_context()`
3. Pre-built `cognitive_trace` dict with vault fields
4. `cognitive_trace=cognitive_trace` in the `_build_surface_response` call

### Step 5A — Write failing integration tests

- [ ] **Step 1: Open tests/test_surface_behavior_layer.py**

  Find the section "MSO Direct Cognitive Generation Tests" (around line 791). Append the following 5 new tests **after** the existing cognitive generation tests (after the last test in that section, before the HTTP tests).

  ```python
  # ---------------------------------------------------------------------------
  # Alpha Phase 3: Vault context wiring tests (tests 10, 13, 14, 15)
  # ---------------------------------------------------------------------------

  @patch("assistant_os.surface_behavior._call_mso_cognitive")
  @patch("assistant_os.surface_behavior._get_vault_context")
  def test_mso_direct_cognitive_includes_vault_trace_when_enabled(
      mock_vault, mock_cognitive
  ):
      """Test 10: mso_direct cognitive path includes vault_context fields in cognitive_trace."""
      mock_vault.return_value = {
          "enabled": True,
          "query": "test",
          "retrieval_method": "keyword_topk",
          "chunks": [
              {
                  "note_path": "/vault/doc.md",
                  "title": "Doc",
                  "tags": [],
                  "frontmatter": {},
                  "content": "test content",
                  "score": 0.8,
              }
          ],
          "vault_sources": ["/vault/doc.md"],
          "vault_chunks_used": 1,
          "token_budget_used": 10,
          "truncated": False,
          "warnings": [],
      }
      mock_cognitive.return_value = {
          "status": "ok",
          "text": "Vault-informed response",
          "provider_name": "anthropic",
          "model_name": "test-model",
          "metadata": {"tokens_in": 100, "tokens_out": 50},
          "used_execution": False,
          "cognitive_only": True,
      }
      resp = get_surface_behavior_response(
          text="explica el modo económico y sus capacidades",
          surface="mso_direct",
          context_id="test-vault-01",
          identity={"operator_id": "test"},
          guard_result=None,
      )
      assert resp is not None
      ct = resp.get("cognitive_trace", {})
      assert ct.get("vault_enabled") is True
      assert ct.get("vault_chunks_used") == 1
      assert ct.get("vault_sources") == ["/vault/doc.md"]
      assert ct.get("vault_retrieval_method") == "keyword_topk"
      assert ct.get("vault_warnings") == []
      assert ct.get("vault_truncated") is False


  @patch("assistant_os.surface_behavior._call_mso_cognitive")
  @patch("assistant_os.surface_behavior._get_vault_context")
  def test_mso_direct_cognitive_vault_disabled_trace(mock_vault, mock_cognitive):
      """Vault fields are present in trace even when vault is disabled."""
      mock_vault.return_value = {
          "enabled": False,
          "query": "test",
          "retrieval_method": "keyword_topk",
          "chunks": [],
          "vault_sources": [],
          "vault_chunks_used": 0,
          "token_budget_used": 0,
          "truncated": False,
          "warnings": [],
      }
      mock_cognitive.return_value = {
          "status": "ok",
          "text": "Response without vault",
          "provider_name": "anthropic",
          "model_name": "test-model",
          "metadata": {"tokens_in": 80, "tokens_out": 40},
          "used_execution": False,
          "cognitive_only": True,
      }
      resp = get_surface_behavior_response(
          text="explica el modo económico y sus capacidades",
          surface="mso_direct",
          context_id="test-vault-02",
          identity={"operator_id": "test"},
          guard_result=None,
      )
      assert resp is not None
      ct = resp.get("cognitive_trace", {})
      assert ct.get("vault_enabled") is False
      assert ct.get("vault_chunks_used") == 0


  @patch("assistant_os.surface_behavior._call_mso_cognitive")
  @patch("assistant_os.surface_behavior._get_vault_context")
  def test_alpha1_provenance_fields_intact_with_vault(mock_vault, mock_cognitive):
      """Test 13: Alpha 1 provenance fields remain intact when vault is wired."""
      mock_vault.return_value = {
          "enabled": True, "query": "test", "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      }
      mock_cognitive.return_value = {
          "status": "ok",
          "text": "Alpha 1 still works",
          "provider_name": "anthropic",
          "model_name": "test-model",
          "metadata": {"tokens_in": 90, "tokens_out": 45},
          "used_execution": False,
          "cognitive_only": True,
      }
      resp = get_surface_behavior_response(
          text="explica el modo económico y sus capacidades",
          surface="mso_direct",
          context_id="test-alpha1",
          identity={"operator_id": "test"},
          guard_result=None,
      )
      assert resp is not None
      ct = resp.get("cognitive_trace", {})
      # Alpha 1 fields
      assert ct.get("response_source") == "llm_economic"
      assert ct.get("execution_status") == "real"
      assert ct.get("provider_used") == "anthropic"
      assert ct.get("model_used") == "test-model"
      assert ct.get("cognitive_generation") is True
      assert ct.get("fallback_used") is False
      assert "latency_ms" in ct
      assert ct.get("tokens_in") == 90
      assert ct.get("tokens_out") == 45
      assert ct.get("execution_allowed") is False
      assert ct.get("can_execute_now") is False


  @patch("assistant_os.surface_behavior._call_mso_cognitive")
  @patch("assistant_os.surface_behavior._get_vault_context")
  def test_alpha2_perception_frame_intact_with_vault(mock_vault, mock_cognitive):
      """Test 14: Alpha 2 perception frame fields remain intact in narrative_context."""
      mock_vault.return_value = {
          "enabled": False, "query": "test", "retrieval_method": "keyword_topk",
          "chunks": [], "vault_sources": [], "vault_chunks_used": 0,
          "token_budget_used": 0, "truncated": False, "warnings": [],
      }
      mock_cognitive.return_value = {
          "status": "ok",
          "text": "Alpha 2 still works",
          "provider_name": "anthropic",
          "model_name": "test-model",
          "metadata": {"tokens_in": 70, "tokens_out": 35},
          "used_execution": False,
          "cognitive_only": True,
      }
      resp = get_surface_behavior_response(
          text="explica el modo económico y sus capacidades",
          surface="mso_direct",
          context_id="test-alpha2",
          identity={"operator_id": "test"},
          guard_result=None,
      )
      assert resp is not None
      nc = resp.get("narrative_context", {})
      # Alpha 2 fields (from build_mso_grounding_context)
      assert nc.get("execution_allowed") is False
      assert nc.get("can_execute_now") is False
      assert "operational_mode" in nc
      assert "seat_provider" in nc
      assert "prepared_actions_count" in nc
      assert "authority_posture" in nc
      assert "limitations" in nc


  def test_no_authority_police_machine_operator_imports_in_vault_modules():
      """Test 15: vault.py and vault_context.py do not import from restricted modules."""
      import ast
      from pathlib import Path

      restricted = {"police", "authority", "machine_operator"}
      vault_files = [
          Path("assistant_os/mso/vault.py"),
          Path("assistant_os/mso/vault_context.py"),
      ]
      for vf in vault_files:
          tree = ast.parse(vf.read_text())
          for node in ast.walk(tree):
              if isinstance(node, (ast.Import, ast.ImportFrom)):
                  module = ""
                  if isinstance(node, ast.ImportFrom) and node.module:
                      module = node.module
                  elif isinstance(node, ast.Import):
                      module = " ".join(alias.name for alias in node.names)
                  for r in restricted:
                      assert r not in module, (
                          f"{vf} imports from restricted module '{r}': {module}"
                      )
  ```

- [ ] **Step 2: Run to confirm tests fail**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v -k "vault" 2>&1 | tail -20
  ```
  Expected: FAIL — `_get_vault_context` not yet defined in `surface_behavior`.

### Step 5B — Wire vault into surface_behavior.py

- [ ] **Step 3: Read surface_behavior.py lines 1068–1083 to confirm exact content**

  Confirm the `_call_mso_cognitive` function is at lines 1073–1080 with signature:
  ```python
  def _call_mso_cognitive(grounding_context: dict, text: str) -> dict:
  ```

- [ ] **Step 4: Add `_get_vault_context` wrapper after `_call_mso_cognitive`**

  Find the block ending at line 1080:
  ```python
      from .mso.mso_chat_provider import call_mso_chat_provider
      return call_mso_chat_provider(grounding_context=grounding_context, user_text=text)
  ```

  Immediately after the closing of `_call_mso_cognitive` (before the `# Public interface` comment), insert:

  ```python

  def _get_vault_context(query: str) -> dict:
      """Thin wrapper around vault_context.build_vault_context for clean test patching."""
      from .mso.vault_context import build_vault_context
      return build_vault_context(query=query)

  ```

- [ ] **Step 5: Replace the cognitive generation block in the mso_direct path**

  Find this exact block (lines ~1247–1283):

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
  ```

  Replace with:

  ```python
          # Cognitive generation path (Sprint 3) — provider-backed, fails closed
          try:
              import time as _time
              from .mso.narrative_runtime import build_mso_grounding_context, build_narrative_context_message
              grounding = build_mso_grounding_context()
              vault_ctx = _get_vault_context(query=text)
              grounding_with_vault = {**grounding, "vault_context": vault_ctx}
              _provider_ok = False
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
  ```

  **Note:** Only the `grounding` → `grounding_with_vault` expansion and `cognitive_trace` dict are new. The fallback block (lines ~1291–1308) stays unchanged.

- [ ] **Step 6: Run the vault integration tests**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v -k "vault" 2>&1 | tail -30
  ```
  Expected: all 5 new vault tests pass.

- [ ] **Step 7: Run the full surface behavior test suite**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v 2>&1 | tail -30
  ```
  Expected: all existing tests still pass (no regressions).

- [ ] **Step 8: Commit**

  ```bash
  git add assistant_os/surface_behavior.py tests/test_surface_behavior_layer.py
  git commit -m "feat(surface): wire Vault context into mso_direct cognitive path (Alpha Phase 3)"
  ```

---

## Task 6: Create `tests/test_economic_perception.py`

This file covers the economic perception frame (Alpha Phase 2) which has no dedicated test file. The sprint's test suite references it. Required to make `pytest tests/test_economic_perception.py` pass.

**Files:**
- Create: `tests/test_economic_perception.py`

- [ ] **Step 1: Create tests/test_economic_perception.py**

  ```python
  """Tests for MSO Economic Perception Frame — Alpha Phase 2 baseline.

  Covers build_mso_grounding_context(), build_narrative_context_message(),
  and is_mso_narrative_intent() in isolation.
  """

  from __future__ import annotations

  import pytest
  from unittest.mock import patch


  # ---------------------------------------------------------------------------
  # Grounding context shape
  # ---------------------------------------------------------------------------

  def test_grounding_context_has_required_keys():
      from assistant_os.mso.narrative_runtime import build_mso_grounding_context
      ctx = build_mso_grounding_context()
      required = {
          "operational_mode", "seat_provider", "prepared_actions_count",
          "next_safe_step", "authority_posture", "limitations",
      }
      assert required.issubset(ctx.keys())


  def test_grounding_context_execution_invariants():
      from assistant_os.mso.narrative_runtime import build_mso_grounding_context
      ctx = build_mso_grounding_context()
      assert ctx.get("execution_allowed") is False
      assert ctx.get("can_execute_now") is False
      assert ctx.get("execution_closed") is True


  def test_grounding_context_never_raises():
      from assistant_os.mso.narrative_runtime import build_mso_grounding_context
      try:
          ctx = build_mso_grounding_context()
          assert isinstance(ctx, dict)
      except Exception as exc:
          pytest.fail(f"build_mso_grounding_context() raised: {exc}")


  # ---------------------------------------------------------------------------
  # Narrative context message
  # ---------------------------------------------------------------------------

  def test_narrative_context_message_returns_str_and_dict():
      from assistant_os.mso.narrative_runtime import build_narrative_context_message
      msg, ctx = build_narrative_context_message()
      assert isinstance(msg, str)
      assert len(msg) > 0
      assert isinstance(ctx, dict)


  def test_narrative_context_message_execution_invariants():
      from assistant_os.mso.narrative_runtime import build_narrative_context_message
      _msg, ctx = build_narrative_context_message()
      assert ctx.get("execution_allowed") is False
      assert ctx.get("can_execute_now") is False


  def test_narrative_context_message_contains_grounding_keys():
      from assistant_os.mso.narrative_runtime import build_narrative_context_message
      _msg, ctx = build_narrative_context_message()
      assert "operational_mode" in ctx
      assert "seat_provider" in ctx


  # ---------------------------------------------------------------------------
  # Narrative intent detection
  # ---------------------------------------------------------------------------

  def test_narrative_intent_detects_known_phrases():
      from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
      known = ["como quedamos", "que hay pendiente", "resumen operacional", "que sigue"]
      for phrase in known:
          assert is_mso_narrative_intent(phrase), f"Expected narrative intent for: {phrase!r}"


  def test_narrative_intent_rejects_executive_phrases():
      from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
      non_narrative = ["crea un archivo", "ejecuta el plan", "abre el repo"]
      for phrase in non_narrative:
          assert not is_mso_narrative_intent(phrase), f"Expected NOT narrative for: {phrase!r}"


  def test_narrative_intent_never_raises():
      from assistant_os.mso.narrative_runtime import is_mso_narrative_intent
      for bad_input in [None, 123, "", "   "]:
          try:
              result = is_mso_narrative_intent(bad_input)  # type: ignore
              assert isinstance(result, bool)
          except Exception as exc:
              pytest.fail(f"is_mso_narrative_intent({bad_input!r}) raised: {exc}")


  # ---------------------------------------------------------------------------
  # System prompt execution boundary
  # ---------------------------------------------------------------------------

  def test_system_prompt_contains_execution_boundary():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      from assistant_os.mso.narrative_runtime import build_mso_grounding_context
      ctx = build_mso_grounding_context()
      prompt = build_mso_chat_system_prompt(ctx)
      assert "cannot execute" in prompt.lower() or "You cannot execute" in prompt


  def test_system_prompt_contains_operational_mode():
      from assistant_os.mso.prompts import build_mso_chat_system_prompt
      from assistant_os.mso.narrative_runtime import build_mso_grounding_context
      ctx = build_mso_grounding_context()
      prompt = build_mso_chat_system_prompt(ctx)
      assert "operational_mode" in prompt.lower() or ctx["operational_mode"] in prompt
  ```

- [ ] **Step 2: Run test_economic_perception.py**

  ```bash
  python -m pytest tests/test_economic_perception.py -v
  ```
  Expected: all tests pass (these test Alpha 2 code that already exists).

- [ ] **Step 3: Commit**

  ```bash
  git add tests/test_economic_perception.py
  git commit -m "test(economic_perception): add Alpha Phase 2 perception frame test coverage"
  ```

---

## Task 7: Final validation — run all required test suites

- [ ] **Step 1: Run test_vault_context.py**

  ```bash
  python -m pytest tests/test_vault_context.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 2: Run test_economic_perception.py**

  ```bash
  python -m pytest tests/test_economic_perception.py -v
  ```
  Expected: all tests pass.

- [ ] **Step 3: Run test_surface_behavior_layer.py**

  ```bash
  python -m pytest tests/test_surface_behavior_layer.py -v
  ```
  Expected: all tests pass (no regressions from Alpha 1 or 2).

- [ ] **Step 4: Run test_ui_runtime_truth_contracts.py (if it exists)**

  ```bash
  python -m pytest tests/test_ui_runtime_truth_contracts.py -v 2>&1 | tail -20
  ```
  Expected: all existing tests pass. (No UI files were modified in this sprint.)

- [ ] **Step 5: Run full test suite to check for any cross-module regression**

  ```bash
  python -m pytest --tb=short -q 2>&1 | tail -30
  ```
  Expected: no new failures introduced.

- [ ] **Step 6: Final commit if any loose files remain**

  ```bash
  git status
  ```
  All files should be committed. If any remain, commit with:
  ```bash
  git add <file>
  git commit -m "chore: finalize Alpha Phase 3 Vault Context Layer v0"
  ```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|-----------------|------|
| `ASSISTANT_OS_VAULT_PATH` config var | Task 1 |
| Vault disabled when path unset → null/empty context | Tasks 3, test 8 |
| `vault_chunks_used=0`, `vault_sources=[]` when disabled | Tasks 3, 5, tests 8, 10 |
| `vault.py`: VaultChunk, VaultNote, VaultReader | Task 2 |
| `vault.py`: parse_frontmatter | Task 2, tests 1–2 |
| `vault.py`: list_markdown_notes (hidden dir skip) | Task 2, test 3 |
| `vault.py`: read_note | Task 2 |
| `vault.py`: keyword_search (top_k, token budget, exclude deprecated) | Task 2, tests 4–7 |
| Frontmatter fields: title, domain, type, priority, tags, status, etc. | Task 2 (parse_frontmatter) |
| Stable preferred, deprecated excluded by default | Task 2, tests 4–5 |
| No frontmatter → allowed but scored lower | Task 2, test 5b |
| `vault_context.py`: build_vault_context shape | Task 3 |
| Economic defaults top_k=3, ~800 token budget | Task 3 (constants) |
| Fail-safe: no raise from build_vault_context | Task 3, tests 8–9 |
| Wire vault into mso_direct cognitive path | Task 5 |
| Vault context in grounding_context → system prompt | Tasks 4, 5 |
| Separate SYSTEM PERCEPTION FRAME from VAULT section | Task 4 (prompt) |
| Prompt rules: vault as doctrine, not execution authority | Task 4 |
| `cognitive_trace` vault fields (6 new fields) | Task 5, test 10 |
| Alpha 1 fields intact | Task 5, test 13 |
| Alpha 2 fields intact | Task 5, test 14 |
| No authority/Police/Machine Operator touched | Task 5, test 15 |
| `test_vault_context.py` with 15 required tests | Tasks 2–5 |
| `test_economic_perception.py` | Task 6 |
| `test_surface_behavior_layer.py` updated | Task 5 |
| No new LLM calls | Confirmed — vault is local file I/O only |
| Vault is read-only | Confirmed — vault.py has no write operations |

### Known limitations

- Keyword search is bag-of-words only (no semantic ranking). Sufficient for v0.
- Block-list frontmatter parsing handles `  - item` format; deeply nested YAML is not supported.
- Token budget is a character approximation (×4), not a true tokenizer count.
- `test_economic_perception.py` `test_narrative_intent_detects_known_phrases` relies on the exact phrases in `_NARRATIVE_EXACT` frozenset — if that set changes, the test must be updated.
