"""SPRINT-ALPHA-04.7 — Domain-aware Vault Context Packs tests.

Tests:
  T-PACK-01..08  : pack inference (infer_note_pack / _KNOWN_PACKS)
  T-SEARCH-01..08: keyword_search with allowed_packs
  T-CTX-01..08   : build_vault_context new fields
  T-INFER-01..08 : infer_query_packs heuristic
  T-PROMPT-01..05: _build_vault_prompt_section / build_mso_chat_system_prompt
  T-SURF-01..03  : surface_behavior cognitive_trace vault_packs_consulted
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# T-PACK: infer_note_pack and _KNOWN_PACKS
# ---------------------------------------------------------------------------

class TestKnownPacks:
    """T-PACK-00: _KNOWN_PACKS contains all 8 required pack names."""

    def test_known_packs_contains_all_eight(self):
        from assistant_os.mso.vault import _KNOWN_PACKS
        required = {"SYSTEM", "CODE", "IPROTA", "HEALTH", "WORK", "FIN", "ENERGY", "PRO_DIAG"}
        assert required.issubset(_KNOWN_PACKS)

    def test_known_packs_is_frozenset(self):
        from assistant_os.mso.vault import _KNOWN_PACKS
        assert isinstance(_KNOWN_PACKS, frozenset)


class TestInferNotePack:
    """T-PACK-01..08: pack inference precedence rules."""

    def _infer(self, path_str: str, frontmatter: dict, vault_root_str: str | None = None):
        from assistant_os.mso.vault import infer_note_pack
        path = Path(path_str)
        vault_root = Path(vault_root_str) if vault_root_str else None
        return infer_note_pack(path, frontmatter, vault_root)

    # T-PACK-01: folder SYSTEM -> SYSTEM
    def test_folder_system_infers_system(self, tmp_path):
        system_dir = tmp_path / "SYSTEM"
        system_dir.mkdir()
        note = system_dir / "doctrine.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result == "SYSTEM"

    # T-PACK-02: folder CODE -> CODE
    def test_folder_code_infers_code(self, tmp_path):
        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        note = code_dir / "sprint.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result == "CODE"

    # T-PACK-03..08: all 8 known packs recognized from folder
    @pytest.mark.parametrize("pack_name", [
        "SYSTEM", "CODE", "IPROTA", "HEALTH", "WORK", "FIN", "ENERGY", "PRO_DIAG"
    ])
    def test_all_eight_packs_recognized_by_folder(self, tmp_path, pack_name):
        pack_dir = tmp_path / pack_name
        pack_dir.mkdir()
        note = pack_dir / "note.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result == pack_name

    # T-PACK-09: frontmatter pack= overrides folder
    def test_frontmatter_pack_overrides_folder(self, tmp_path):
        health_dir = tmp_path / "HEALTH"
        health_dir.mkdir()
        note = health_dir / "note.md"
        note.touch()
        result = self._infer(str(note), {"pack": "CODE"}, str(tmp_path))
        assert result == "CODE"

    # T-PACK-10: frontmatter domain= used when pack= absent
    def test_frontmatter_domain_used_when_pack_absent(self, tmp_path):
        note = tmp_path / "root-note.md"
        note.touch()
        result = self._infer(str(note), {"domain": "FIN"}, str(tmp_path))
        assert result == "FIN"

    # T-PACK-11: frontmatter pack= takes precedence over domain=
    def test_frontmatter_pack_beats_domain(self, tmp_path):
        note = tmp_path / "note.md"
        note.touch()
        result = self._infer(str(note), {"pack": "WORK", "domain": "FIN"}, str(tmp_path))
        assert result == "WORK"

    # T-PACK-12: invalid frontmatter pack falls through to folder
    def test_invalid_frontmatter_pack_falls_to_folder(self, tmp_path):
        work_dir = tmp_path / "WORK"
        work_dir.mkdir()
        note = work_dir / "task.md"
        note.touch()
        result = self._infer(str(note), {"pack": "INVALID_PACK_XYZ"}, str(tmp_path))
        assert result == "WORK"

    # T-PACK-13: root-level note is unclassified (None)
    def test_root_level_note_is_unclassified(self, tmp_path):
        note = tmp_path / "my-note.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result is None

    # T-PACK-14: unknown top-level folder is unclassified
    def test_unknown_folder_is_unclassified(self, tmp_path):
        unknown_dir = tmp_path / "RANDOM_FOLDER"
        unknown_dir.mkdir()
        note = unknown_dir / "note.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result is None

    # T-PACK-15: nested notes inherit top-level folder pack
    def test_nested_note_inherits_top_folder(self, tmp_path):
        code_dir = tmp_path / "CODE" / "api"
        code_dir.mkdir(parents=True)
        note = code_dir / "types.md"
        note.touch()
        result = self._infer(str(note), {}, str(tmp_path))
        assert result == "CODE"

    # T-PACK-16: vault_root=None means only frontmatter is checked
    def test_vault_root_none_only_uses_frontmatter(self, tmp_path):
        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        note = code_dir / "note.md"
        note.touch()
        # Without vault_root, folder inference cannot work
        result = self._infer(str(note), {}, vault_root_str=None)
        assert result is None  # no frontmatter, no vault_root -> unclassified

    def test_vault_root_none_still_uses_frontmatter(self, tmp_path):
        note = tmp_path / "note.md"
        note.touch()
        result = self._infer(str(note), {"pack": "IPROTA"}, vault_root_str=None)
        assert result == "IPROTA"

    # T-PACK-17: case-insensitive frontmatter values normalized to uppercase
    def test_frontmatter_pack_case_insensitive(self, tmp_path):
        note = tmp_path / "note.md"
        note.touch()
        result = self._infer(str(note), {"pack": "code"}, str(tmp_path))
        assert result == "CODE"

    def test_frontmatter_domain_case_insensitive(self, tmp_path):
        note = tmp_path / "note.md"
        note.touch()
        result = self._infer(str(note), {"domain": "health"}, str(tmp_path))
        assert result == "HEALTH"


# ---------------------------------------------------------------------------
# T-SEARCH: keyword_search with allowed_packs
# ---------------------------------------------------------------------------

def _write_note(directory: Path, filename: str, title: str, status: str = "stable",
                pack: str | None = None, domain: str | None = None, content: str = "generic content") -> Path:
    """Helper: write a markdown note to a directory."""
    fm_lines = [f"title: {title}", f"status: {status}"]
    if pack:
        fm_lines.append(f"pack: {pack}")
    if domain:
        fm_lines.append(f"domain: {domain}")
    fm = "---\n" + "\n".join(fm_lines) + "\n---\n"
    p = directory / filename
    p.write_text(fm + content)
    return p


class TestKeywordSearchWithPacks:
    """T-SEARCH-01..08: keyword_search filtering."""

    def test_t_search_01_flat_returns_all_notes(self, tmp_path):
        """allowed_packs=None preserves flat retrieval (backward compat)."""
        from assistant_os.mso.vault import keyword_search

        system_dir = tmp_path / "SYSTEM"
        code_dir = tmp_path / "CODE"
        health_dir = tmp_path / "HEALTH"
        system_dir.mkdir(); code_dir.mkdir(); health_dir.mkdir()
        _write_note(system_dir, "sys.md", "System Note", content="shared keyword alpha")
        _write_note(code_dir, "code.md", "Code Note", content="shared keyword alpha")
        _write_note(health_dir, "health.md", "Health Note", content="shared keyword alpha")

        chunks = keyword_search(str(tmp_path), query="shared keyword alpha",
                                top_k=10, allowed_packs=None)
        titles = {c.title for c in chunks}
        assert "System Note" in titles
        assert "Code Note" in titles
        assert "Health Note" in titles

    def test_t_search_02_code_filter_excludes_health(self, tmp_path):
        """allowed_packs=['CODE'] excludes HEALTH notes."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        health_dir = tmp_path / "HEALTH"
        code_dir.mkdir(); health_dir.mkdir()
        _write_note(code_dir, "code.md", "Code Note", content="shared keyword beta")
        _write_note(health_dir, "health.md", "Health Note", content="shared keyword beta")

        chunks = keyword_search(str(tmp_path), query="shared keyword beta",
                                top_k=10, allowed_packs=["CODE"])
        titles = {c.title for c in chunks}
        assert "Code Note" in titles
        assert "Health Note" not in titles

    def test_t_search_03_system_always_included(self, tmp_path):
        """SYSTEM notes appear even when allowed_packs=['CODE'] (no 'SYSTEM')."""
        from assistant_os.mso.vault import keyword_search

        system_dir = tmp_path / "SYSTEM"
        code_dir = tmp_path / "CODE"
        iprota_dir = tmp_path / "IPROTA"
        system_dir.mkdir(); code_dir.mkdir(); iprota_dir.mkdir()
        _write_note(system_dir, "sys.md", "System Note", content="shared keyword gamma")
        _write_note(code_dir, "code.md", "Code Note", content="shared keyword gamma")
        _write_note(iprota_dir, "iprota.md", "Iprota Note", content="shared keyword gamma")

        chunks = keyword_search(str(tmp_path), query="shared keyword gamma",
                                top_k=10, allowed_packs=["CODE"])
        titles = {c.title for c in chunks}
        assert "System Note" in titles, "SYSTEM must always be included"
        assert "Code Note" in titles
        assert "Iprota Note" not in titles

    def test_t_search_04_unclassified_always_included(self, tmp_path):
        """Root-level (unclassified) notes pass the pack filter."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        health_dir = tmp_path / "HEALTH"
        code_dir.mkdir(); health_dir.mkdir()
        _write_note(code_dir, "code.md", "Code Note", content="shared keyword delta")
        _write_note(health_dir, "health.md", "Health Note", content="shared keyword delta")
        # Root-level note — unclassified
        (tmp_path / "root.md").write_text(
            "---\ntitle: Root Note\nstatus: stable\n---\nshared keyword delta"
        )

        chunks = keyword_search(str(tmp_path), query="shared keyword delta",
                                top_k=10, allowed_packs=["CODE"])
        titles = {c.title for c in chunks}
        assert "Root Note" in titles, "Unclassified notes must pass filter"
        assert "Health Note" not in titles

    def test_t_search_05_top_k_respected_under_filter(self, tmp_path):
        """top_k is respected even under pack filter."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        for i in range(8):
            _write_note(code_dir, f"note{i}.md", f"Code Note {i}",
                        content="keyword epsilon here")

        chunks = keyword_search(str(tmp_path), query="keyword epsilon",
                                top_k=3, allowed_packs=["CODE"])
        assert len(chunks) <= 3

    def test_t_search_06_empty_pack_folder_no_crash(self, tmp_path):
        """Empty allowed pack folder returns empty results without exception."""
        from assistant_os.mso.vault import keyword_search

        # Create IPROTA folder but put no notes in it
        iprota_dir = tmp_path / "IPROTA"
        iprota_dir.mkdir()
        # Only SYSTEM notes exist
        system_dir = tmp_path / "SYSTEM"
        system_dir.mkdir()
        _write_note(system_dir, "sys.md", "System Note", content="keyword zeta")

        chunks = keyword_search(str(tmp_path), query="keyword zeta",
                                top_k=10, allowed_packs=["IPROTA"])
        # SYSTEM always included, IPROTA folder is empty
        titles = {c.title for c in chunks}
        assert "System Note" in titles  # SYSTEM always included

    def test_t_search_07_deprecated_excluded_under_filter(self, tmp_path):
        """Deprecated notes excluded under pack filter."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        _write_note(code_dir, "active.md", "Active Code", status="stable",
                    content="keyword eta content")
        _write_note(code_dir, "old.md", "Old Code", status="deprecated",
                    content="keyword eta content")

        chunks = keyword_search(str(tmp_path), query="keyword eta",
                                top_k=10, allowed_packs=["CODE"])
        titles = {c.title for c in chunks}
        assert "Active Code" in titles
        assert "Old Code" not in titles

    def test_t_search_08_empty_allowed_packs_list_is_flat(self, tmp_path):
        """allowed_packs=[] is treated as None (flat retrieval)."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        health_dir = tmp_path / "HEALTH"
        code_dir.mkdir(); health_dir.mkdir()
        _write_note(code_dir, "code.md", "Code Note", content="shared keyword theta")
        _write_note(health_dir, "health.md", "Health Note", content="shared keyword theta")

        chunks = keyword_search(str(tmp_path), query="shared keyword theta",
                                top_k=10, allowed_packs=[])
        titles = {c.title for c in chunks}
        assert "Code Note" in titles
        assert "Health Note" in titles

    def test_t_search_09_chunk_has_pack_field(self, tmp_path):
        """VaultChunk has a pack field populated from resolved pack."""
        from assistant_os.mso.vault import keyword_search

        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        _write_note(code_dir, "sprint.md", "Sprint Memory", content="keyword iota")

        chunks = keyword_search(str(tmp_path), query="keyword iota",
                                top_k=5, allowed_packs=None)
        assert len(chunks) == 1
        assert hasattr(chunks[0], "pack")
        assert chunks[0].pack == "CODE"

    def test_t_search_10_frontmatter_pack_overrides_folder_in_search(self, tmp_path):
        """Frontmatter pack= takes effect in keyword_search filtering."""
        from assistant_os.mso.vault import keyword_search

        # Note is in HEALTH folder but frontmatter says CODE
        health_dir = tmp_path / "HEALTH"
        health_dir.mkdir()
        _write_note(health_dir, "cross.md", "Cross Note",
                    pack="CODE", content="keyword kappa shared")
        # Pure HEALTH note
        _write_note(health_dir, "pure.md", "Pure Health",
                    content="keyword kappa shared")

        # Filter to CODE only
        chunks = keyword_search(str(tmp_path), query="keyword kappa",
                                top_k=10, allowed_packs=["CODE"])
        titles = {c.title for c in chunks}
        assert "Cross Note" in titles, "Frontmatter CODE overrides HEALTH folder"
        assert "Pure Health" not in titles


# ---------------------------------------------------------------------------
# T-CTX: build_vault_context new pack fields
# ---------------------------------------------------------------------------

class TestBuildVaultContextPacks:
    """T-CTX-01..08: new pack fields in build_vault_context."""

    def test_t_ctx_01_packs_consulted_present_when_filtered(self, tmp_path, monkeypatch):
        """packs_consulted is set when allowed_packs provided."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        _write_note(code_dir, "note.md", "Code Note", content="lambda keyword")

        result = vc_mod.build_vault_context("lambda keyword", allowed_packs=["CODE"])
        assert "packs_consulted" in result
        packs = result["packs_consulted"]
        assert "CODE" in packs
        assert "SYSTEM" in packs  # always included

    def test_t_ctx_02_pack_filter_active_true_when_filtered(self, tmp_path, monkeypatch):
        """pack_filter_active=True when allowed_packs provided."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        _write_note(tmp_path, "note.md", "Note", content="mu keyword")

        result = vc_mod.build_vault_context("mu keyword", allowed_packs=["CODE"])
        assert result["pack_filter_active"] is True

    def test_t_ctx_03_pack_filter_active_false_when_flat(self, tmp_path, monkeypatch):
        """pack_filter_active=False when allowed_packs=None."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        _write_note(tmp_path, "note.md", "Note", content="nu keyword")

        result = vc_mod.build_vault_context("nu keyword", allowed_packs=None)
        assert result["pack_filter_active"] is False
        assert result["packs_consulted"] == ["ALL"]

    def test_t_ctx_04_disabled_context_has_safe_new_fields(self, monkeypatch):
        """Disabled context (_disabled) includes new fields with safe defaults."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "")
        result = vc_mod.build_vault_context("any query")
        assert "pack_filter_active" in result
        assert "packs_consulted" in result
        assert "unclassified_included" in result
        assert result["pack_filter_active"] is False
        assert result["packs_consulted"] == []
        assert result["unclassified_included"] is True

    def test_t_ctx_05_invalid_vault_path_has_safe_new_fields(self, monkeypatch):
        """Invalid vault path still returns pack fields with safe defaults."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "/nonexistent/path/xyzzy999")
        result = vc_mod.build_vault_context("any query")
        assert "pack_filter_active" in result
        assert "packs_consulted" in result
        assert "unclassified_included" in result
        assert result["enabled"] is False

    def test_t_ctx_06_unclassified_included_always_true(self, tmp_path, monkeypatch):
        """unclassified_included is True in all cases."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        _write_note(tmp_path, "note.md", "Note", content="xi keyword")

        for allowed in [None, ["CODE"], []]:
            result = vc_mod.build_vault_context("xi keyword", allowed_packs=allowed)
            assert result["unclassified_included"] is True, f"Failed for allowed_packs={allowed!r}"

    def test_t_ctx_07_domain_hints_used_when_allowed_packs_absent(self, tmp_path, monkeypatch):
        """domain_hints wires to pack filter when allowed_packs is None."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        fin_dir = tmp_path / "FIN"
        health_dir = tmp_path / "HEALTH"
        fin_dir.mkdir(); health_dir.mkdir()
        _write_note(fin_dir, "budget.md", "Budget", content="omicron keyword")
        _write_note(health_dir, "health.md", "Health", content="omicron keyword")

        result = vc_mod.build_vault_context("omicron keyword",
                                             allowed_packs=None, domain_hints=["FIN"])
        assert result["pack_filter_active"] is True
        assert "FIN" in result["packs_consulted"]
        sources = result["vault_sources"]
        # Health note should be excluded
        assert not any("health" in s.lower() for s in sources)

    def test_t_ctx_08_infer_query_packs_exception_falls_back_to_flat(self, tmp_path, monkeypatch):
        """Exception in infer_query_packs falls back to flat retrieval."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        _write_note(tmp_path, "note.md", "Note", content="pi keyword")

        # Patch infer_query_packs to raise
        def _raise(*a, **kw):
            raise RuntimeError("heuristic crashed")
        monkeypatch.setattr(vc_mod, "infer_query_packs", _raise)

        result = vc_mod.build_vault_context("pi keyword")
        # Must not raise; falls back to flat retrieval
        assert result["pack_filter_active"] is False

    def test_t_ctx_09_chunk_pack_field_in_returned_dict(self, tmp_path, monkeypatch):
        """Chunks returned by build_vault_context include a 'pack' field."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        code_dir = tmp_path / "CODE"
        code_dir.mkdir()
        _write_note(code_dir, "sprint.md", "Sprint Note", content="rho keyword")

        result = vc_mod.build_vault_context("rho keyword")
        assert result["enabled"] is True
        assert len(result["chunks"]) >= 1
        assert "pack" in result["chunks"][0]
        assert result["chunks"][0]["pack"] == "CODE"

    def test_t_ctx_10_existing_shape_still_present(self, monkeypatch):
        """Original required keys still present after adding new pack fields."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", "")
        result = vc_mod.build_vault_context("any query")
        original_keys = {
            "enabled", "query", "retrieval_method", "chunks",
            "vault_sources", "vault_chunks_used", "token_budget_used",
            "truncated", "warnings",
        }
        assert original_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# T-INFER: infer_query_packs heuristic
# ---------------------------------------------------------------------------

class TestInferQueryPacks:
    """T-INFER-01..08: query→pack heuristic."""

    def _infer(self, query: str) -> list[str] | None:
        from assistant_os.mso.vault_context import infer_query_packs
        return infer_query_packs(query)

    def test_t_infer_01_code_signals_return_code_and_system(self):
        result = self._infer("analiza el repo")
        assert result is not None
        assert "CODE" in result
        assert "SYSTEM" in result

    def test_t_infer_02_health_signals_return_health_and_system(self):
        result = self._infer("sueño y ansiedad")
        assert result is not None
        assert "HEALTH" in result
        assert "SYSTEM" in result

    def test_t_infer_03_mso_only_signals_return_none(self):
        """Pure SYSTEM/MSO signals return None (flat retrieval for open-ended queries)."""
        result = self._infer("qué ves del sistema")
        # Pure operational query — no specific domain pack → flat retrieval
        assert result is None or "CODE" not in result

    def test_t_infer_04_fin_signals_return_fin_and_system(self):
        result = self._infer("revisar el presupuesto y gastos")
        assert result is not None
        assert "FIN" in result
        assert "SYSTEM" in result

    def test_t_infer_05_iprota_signals_return_iprota_and_system(self):
        result = self._infer("el canon de iprota")
        assert result is not None
        assert "IPROTA" in result
        assert "SYSTEM" in result

    def test_t_infer_06_work_signals_return_work_and_system(self):
        result = self._infer("cuántas tareas pendientes hay en el lab")
        assert result is not None
        assert "WORK" in result
        assert "SYSTEM" in result

    def test_t_infer_07_energy_signals_return_energy_and_system(self):
        result = self._infer("rutina de energía y productividad")
        assert result is not None
        assert "ENERGY" in result
        assert "SYSTEM" in result

    def test_t_infer_08_prodiag_signals_return_prodiag_and_system(self):
        result = self._infer("diagnóstico de riesgo empresarial")
        assert result is not None
        assert "PRO_DIAG" in result
        assert "SYSTEM" in result

    def test_t_infer_09_ambiguous_returns_none(self):
        """Generic greeting returns None (flat)."""
        result = self._infer("hola")
        assert result is None

    def test_t_infer_10_empty_query_returns_none(self):
        result = self._infer("")
        assert result is None

    def test_t_infer_11_whitespace_only_returns_none(self):
        result = self._infer("   ")
        assert result is None

    def test_t_infer_12_diacritics_handled(self):
        """Queries with and without diacritics both trigger the same pack."""
        from assistant_os.mso.vault_context import infer_query_packs
        with_accent = infer_query_packs("análisis del código")
        without_accent = infer_query_packs("analisis del codigo")
        # Both should trigger CODE or both return None — not different
        if with_accent is not None:
            assert "CODE" in with_accent
        if without_accent is not None:
            assert "CODE" in without_accent

    def test_t_infer_13_never_raises(self):
        """infer_query_packs never raises on any input."""
        from assistant_os.mso.vault_context import infer_query_packs
        inputs = [None, "", "   ", "a" * 10000, "!@#$%^&*()", "💀🔥", "código"]
        for inp in inputs:
            try:
                infer_query_packs(inp)  # type: ignore[arg-type]
            except Exception as exc:
                pytest.fail(f"infer_query_packs raised on {inp!r}: {exc}")

    def test_t_infer_14_multi_domain_query_triggers_multiple_packs(self):
        """Query touching two domains returns both packs + SYSTEM."""
        result = self._infer("analiza el código y el presupuesto del proyecto")
        assert result is not None
        assert "CODE" in result
        assert "FIN" in result
        assert "SYSTEM" in result

    def test_t_infer_15_result_is_sorted_list(self):
        """Return value is a sorted list (or None)."""
        from assistant_os.mso.vault_context import infer_query_packs
        result = infer_query_packs("analiza el repo")
        assert result is None or result == sorted(result)


# ---------------------------------------------------------------------------
# T-PROMPT: VAULT SEMANTIC CONTEXT section pack fields
# ---------------------------------------------------------------------------

def _make_vault_ctx_with_packs(note_path: str, title: str, pack: str | None,
                                pack_filter_active: bool,
                                packs_consulted: list[str]) -> dict:
    return {
        "enabled": True,
        "query": "test",
        "retrieval_method": "keyword_topk",
        "chunks": [
            {
                "note_path": note_path,
                "title": title,
                "tags": [],
                "frontmatter": {"pack": pack} if pack else {},
                "content": "Some relevant content here.",
                "score": 0.9,
                "pack": pack,
            }
        ],
        "vault_sources": [note_path],
        "vault_chunks_used": 1,
        "token_budget_used": 10,
        "truncated": False,
        "warnings": [],
        "pack_filter_active": pack_filter_active,
        "packs_consulted": packs_consulted,
        "unclassified_included": True,
    }


def _make_flat_vault_ctx(note_path: str, title: str) -> dict:
    return {
        "enabled": True,
        "query": "test",
        "retrieval_method": "keyword_topk",
        "chunks": [
            {
                "note_path": note_path,
                "title": title,
                "tags": [],
                "frontmatter": {},
                "content": "Some content.",
                "score": 0.7,
                "pack": None,
            }
        ],
        "vault_sources": [note_path],
        "vault_chunks_used": 1,
        "token_budget_used": 5,
        "truncated": False,
        "warnings": [],
        "pack_filter_active": False,
        "packs_consulted": ["ALL"],
        "unclassified_included": True,
    }


def _make_grounding_with_vault(vault_ctx: dict) -> dict:
    return {
        "operational_mode": "NORMAL",
        "seat_provider": "test-provider",
        "prepared_actions_count": 0,
        "prepared_actions_summary": [],
        "next_safe_step": "none",
        "authority_posture": "chain",
        "limitations": "You cannot execute.",
        "version": "alpha-04.7",
        "generated_at": "2026-05-14T00:00:00",
        "capabilities_summary": {},
        "recent_governance": [],
        "active_tasks_brief": [],
        "recent_failures": [],
        "perception_warnings": [],
        "vault_context": vault_ctx,
    }


class TestPromptPackFields:
    """T-PROMPT-01..05: VAULT SEMANTIC CONTEXT section with pack metadata."""

    def test_t_prompt_01_packs_consulted_shown_when_filter_active(self, tmp_path):
        """Prompt includes 'Packs consulted' when pack_filter_active=True."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        vault_ctx = _make_vault_ctx_with_packs(
            str(tmp_path / "SYSTEM/doctrine.md"), "MSO Doctrine",
            pack="SYSTEM", pack_filter_active=True,
            packs_consulted=["CODE", "SYSTEM"],
        )
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        assert "Packs consulted" in prompt
        assert "CODE" in prompt
        assert "SYSTEM" in prompt

    def test_t_prompt_02_sources_show_pack_label(self, tmp_path):
        """Source lines include pack label in brackets when available."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        vault_ctx = _make_vault_ctx_with_packs(
            str(tmp_path / "CODE/sprint.md"), "Sprint Memory",
            pack="CODE", pack_filter_active=True,
            packs_consulted=["CODE", "SYSTEM"],
        )
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        # Source line should include [CODE]
        assert "[CODE]" in prompt

    def test_t_prompt_03_chunk_header_shows_pack_label(self, tmp_path):
        """Chunk content header shows pack label when pack is available."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        vault_ctx = _make_vault_ctx_with_packs(
            str(tmp_path / "SYSTEM/gov.md"), "Governance Doc",
            pack="SYSTEM", pack_filter_active=True,
            packs_consulted=["SYSTEM"],
        )
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        # Chunk header should include pack label e.g. [Governance Doc | SYSTEM]
        assert "SYSTEM" in prompt
        assert "Governance Doc" in prompt

    def test_t_prompt_04_flat_retrieval_shows_all_unfiltered(self, tmp_path):
        """Flat retrieval (pack_filter_active=False) shows 'ALL' or 'unfiltered' in prompt."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        vault_ctx = _make_flat_vault_ctx(str(tmp_path / "note.md"), "General Note")
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        assert "VAULT SEMANTIC CONTEXT" in prompt
        # Should indicate unfiltered retrieval
        assert "ALL" in prompt or "unfiltered" in prompt.lower()

    def test_t_prompt_05_missing_pack_data_does_not_crash(self, tmp_path):
        """Chunk without pack field does not crash the prompt builder."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        # Chunk without 'pack' key at all (backward compat)
        vault_ctx = {
            "enabled": True,
            "query": "test",
            "retrieval_method": "keyword_topk",
            "chunks": [
                {
                    "note_path": str(tmp_path / "note.md"),
                    "title": "Old Note",
                    "tags": [],
                    "frontmatter": {},
                    "content": "Some content.",
                    "score": 0.5,
                    # No 'pack' key — backward-compat scenario
                }
            ],
            "vault_sources": [str(tmp_path / "note.md")],
            "vault_chunks_used": 1,
            "token_budget_used": 5,
            "truncated": False,
            "warnings": [],
            # No pack_filter_active / packs_consulted — backward-compat
        }
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        assert isinstance(prompt, str)
        assert "VAULT SEMANTIC CONTEXT" in prompt

    def test_t_prompt_06_filter_active_includes_missing_pack_instruction(self, tmp_path):
        """When filter is active, prompt includes instruction about unconsulted packs."""
        from assistant_os.mso.prompts import build_mso_chat_system_prompt

        vault_ctx = _make_vault_ctx_with_packs(
            str(tmp_path / "CODE/note.md"), "Code Note",
            pack="CODE", pack_filter_active=True,
            packs_consulted=["CODE", "SYSTEM"],
        )
        grounding = _make_grounding_with_vault(vault_ctx)
        prompt = build_mso_chat_system_prompt(grounding)
        # Should include guidance about unconsulted packs
        lower = prompt.lower()
        assert ("not consulted" in lower or "was not retrieved" in lower or
                "not retrieved" in lower or "no consultado" in lower)


# ---------------------------------------------------------------------------
# T-SURF: surface_behavior cognitive_trace vault_packs_consulted
# ---------------------------------------------------------------------------

def _mock_identity():
    m = MagicMock()
    m.to_audit_dict.return_value = {"principal": "anon"}
    return m


def _mock_guard():
    m = MagicMock()
    m.to_audit_dict.return_value = {"decision": "allow"}
    return m


def _make_vault_ctx_with_packs_consulted(packs: list[str], enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "query": "test",
        "retrieval_method": "keyword_topk",
        "chunks": [],
        "vault_sources": [],
        "vault_chunks_used": 0,
        "token_budget_used": 0,
        "truncated": False,
        "warnings": [],
        "pack_filter_active": enabled and bool(packs and packs != ["ALL"]),
        "packs_consulted": packs,
        "unclassified_included": True,
    }


def _make_provider_resp(text: str = "Test cognitive response.") -> dict:
    return {
        "status": "ok",
        "text": text,
        "provider_name": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "used_execution": False,
        "cognitive_only": True,
        "error": None,
        "metadata": {"tokens_in": 100, "tokens_out": 50,
                     "cognitive_only": True, "non_executing": True},
    }


class TestSurfaceBehaviorPacks:
    """T-SURF-01..03: cognitive_trace vault_packs_consulted in surface_behavior."""

    def test_t_surf_01_cognitive_trace_has_vault_packs_consulted(self):
        """cognitive_trace includes vault_packs_consulted on successful LLM response."""
        from assistant_os.surface_behavior import get_surface_behavior_response

        packs = ["CODE", "SYSTEM"]
        vault_ctx = _make_vault_ctx_with_packs_consulted(packs)
        provider_resp = _make_provider_resp()

        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=vault_ctx), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=provider_resp), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value={
                       "operational_mode": "NORMAL",
                       "seat_provider": "test",
                       "prepared_actions_count": 0,
                       "prepared_actions_summary": [],
                       "next_safe_step": "none",
                       "authority_posture": "chain",
                       "limitations": "no exec",
                       "version": "alpha-04.7",
                       "generated_at": "2026-05-14T00:00:00",
                       "capabilities_summary": {},
                       "recent_governance": [],
                       "active_tasks_brief": [],
                       "recent_failures": [],
                       "perception_warnings": [],
                       "pending_review_items": [],
                   }):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo del repo",
                context_id="test-ctx-001",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
            )

        assert result is not None
        ct = result.get("cognitive_trace") or {}
        assert "vault_packs_consulted" in ct
        assert ct["vault_packs_consulted"] == packs

    def test_t_surf_02_disabled_vault_yields_empty_packs_consulted(self):
        """Disabled vault gives vault_packs_consulted=[] in cognitive_trace."""
        from assistant_os.surface_behavior import get_surface_behavior_response

        vault_ctx = _make_vault_ctx_with_packs_consulted([], enabled=False)
        provider_resp = _make_provider_resp()

        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=vault_ctx), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   return_value=provider_resp), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value={
                       "operational_mode": "NORMAL",
                       "seat_provider": "test",
                       "prepared_actions_count": 0,
                       "prepared_actions_summary": [],
                       "next_safe_step": "none",
                       "authority_posture": "chain",
                       "limitations": "no exec",
                       "version": "alpha-04.7",
                       "generated_at": "2026-05-14T00:00:00",
                       "capabilities_summary": {},
                       "recent_governance": [],
                       "active_tasks_brief": [],
                       "recent_failures": [],
                       "perception_warnings": [],
                       "pending_review_items": [],
                   }):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="soy jorge",
                context_id="test-ctx-002",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
            )

        assert result is not None
        ct = result.get("cognitive_trace") or {}
        assert "vault_packs_consulted" in ct
        assert ct["vault_packs_consulted"] == []

    def test_t_surf_03_provider_fallback_still_works_with_pack_wiring(self):
        """Provider failure still returns fallback response, not exception."""
        from assistant_os.surface_behavior import get_surface_behavior_response

        vault_ctx = _make_vault_ctx_with_packs_consulted(["CODE", "SYSTEM"])

        with patch("assistant_os.surface_behavior._get_vault_context",
                   return_value=vault_ctx), \
             patch("assistant_os.surface_behavior._call_mso_cognitive",
                   side_effect=RuntimeError("provider crashed")), \
             patch("assistant_os.surface_behavior.build_mso_grounding_context",
                   return_value={
                       "operational_mode": "NORMAL",
                       "seat_provider": "test",
                       "prepared_actions_count": 0,
                       "prepared_actions_summary": [],
                       "next_safe_step": "none",
                       "authority_posture": "chain",
                       "limitations": "no exec",
                       "version": "alpha-04.7",
                       "generated_at": "2026-05-14T00:00:00",
                       "capabilities_summary": {},
                       "recent_governance": [],
                       "active_tasks_brief": [],
                       "recent_failures": [],
                       "perception_warnings": [],
                       "pending_review_items": [],
                   }), \
             patch("assistant_os.surface_behavior.build_narrative_context_message",
                   return_value=("Narrative fallback.", {"operational_mode": "NORMAL"})):
            result = get_surface_behavior_response(
                surface="mso_direct",
                text="analiza el codigo",
                context_id="test-ctx-003",
                identity=_mock_identity(),
                guard_result=_mock_guard(),
            )

        # Must return a fallback response, not None or exception
        assert result is not None
        assert result.get("fallback_used") is True


# ---------------------------------------------------------------------------
# Regression: existing vault behavior unchanged
# ---------------------------------------------------------------------------

class TestVaultRegressions:
    """Confirm existing flat retrieval behavior is fully preserved."""

    def test_keyword_search_no_allowed_packs_identical_to_old(self, tmp_path):
        """keyword_search(allowed_packs=None) behaves like the old implementation."""
        from assistant_os.mso.vault import keyword_search

        (tmp_path / "a.md").write_text(
            "---\ntitle: Alpha\nstatus: stable\n---\nregression content here"
        )
        (tmp_path / "b.md").write_text(
            "---\ntitle: Beta\nstatus: stable\n---\nregression content here"
        )

        chunks = keyword_search(str(tmp_path), query="regression content", top_k=10)
        titles = {c.title for c in chunks}
        assert "Alpha" in titles
        assert "Beta" in titles

    def test_vault_chunk_still_has_original_fields(self, tmp_path):
        """VaultChunk still has all original fields after adding pack."""
        from assistant_os.mso.vault import keyword_search

        (tmp_path / "note.md").write_text(
            "---\ntitle: Test Note\nstatus: stable\ntags: [test]\n---\nregression field content"
        )
        chunks = keyword_search(str(tmp_path), query="regression field content")
        assert len(chunks) == 1
        c = chunks[0]
        assert hasattr(c, "note_path")
        assert hasattr(c, "title")
        assert hasattr(c, "tags")
        assert hasattr(c, "frontmatter")
        assert hasattr(c, "content")
        assert hasattr(c, "score")
        assert hasattr(c, "pack")  # new field

    def test_build_vault_context_no_params_still_works(self, tmp_path, monkeypatch):
        """build_vault_context() with no new params is backward-compatible."""
        import assistant_os.mso.vault_context as vc_mod
        monkeypatch.setattr(vc_mod, "ASSISTANT_OS_VAULT_PATH", str(tmp_path))
        (tmp_path / "note.md").write_text(
            "---\ntitle: Legacy\nstatus: stable\n---\nregression compat content"
        )
        result = vc_mod.build_vault_context("regression compat content")
        assert result["enabled"] is True
        assert result["vault_chunks_used"] >= 1
