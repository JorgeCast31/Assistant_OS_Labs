"""Read-only Obsidian Vault utilities for MSO semantic context retrieval.

No writes, no embeddings, no Obsidian-specific APIs. Plain Markdown only.
Tolerates missing or malformed frontmatter. Never raises from public functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_KNOWN_PACKS: frozenset[str] = frozenset(
    {"SYSTEM", "CODE", "IPROTA", "HEALTH", "WORK", "FIN", "ENERGY", "PRO_DIAG"}
)


@dataclass
class VaultChunk:
    note_path: str
    title: str
    tags: list[str]
    frontmatter: dict
    content: str
    score: float
    pack: str | None = None


@dataclass
class VaultNote:
    path: Path
    frontmatter: dict
    body: str
    title: str
    tags: list[str]
    status: str
    retrieval_weight: float
    pack: str | None = None


def infer_note_pack(
    path: Path,
    frontmatter: dict,
    vault_root: Path | None = None,
) -> str | None:
    """Infer the domain pack for a note.

    Precedence (highest to lowest):
    1. frontmatter ``pack`` key
    2. frontmatter ``domain`` key
    3. top-level folder name under vault_root (if matches a known pack)
    4. None (unclassified)

    All matches are case-insensitive; returned value is uppercase canonical name.
    Never raises.
    """
    try:
        # 1. Explicit pack frontmatter key
        pack_val = frontmatter.get("pack")
        if pack_val and isinstance(pack_val, str):
            candidate = pack_val.strip().upper()
            if candidate in _KNOWN_PACKS:
                return candidate

        # 2. Domain frontmatter key
        domain_val = frontmatter.get("domain")
        if domain_val and isinstance(domain_val, str):
            candidate = domain_val.strip().upper()
            if candidate in _KNOWN_PACKS:
                return candidate

        # 3. Top-level folder under vault_root
        if vault_root is not None:
            try:
                rel = path.relative_to(vault_root)
                if rel.parts:
                    folder = rel.parts[0].upper()
                    if folder in _KNOWN_PACKS:
                        return folder
            except ValueError:
                pass

        return None
    except Exception:
        return None


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


def read_note(path: Path, vault_root: Path | None = None) -> VaultNote | None:
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

        pack = infer_note_pack(path, frontmatter, vault_root)

        return VaultNote(
            path=path,
            frontmatter=frontmatter,
            body=body,
            title=title,
            tags=tags,
            status=status,
            retrieval_weight=retrieval_weight,
            pack=pack,
        )
    except Exception:
        return None


class VaultReader:
    """Read-only interface to an Obsidian Vault directory."""

    def __init__(self, vault_path: str) -> None:
        self.vault_path = vault_path

    def list_notes(self) -> list[VaultNote]:
        notes = []
        vault_root = Path(self.vault_path)
        for p in list_markdown_notes(self.vault_path):
            note = read_note(p, vault_root=vault_root)
            if note is not None:
                notes.append(note)
        return notes


def keyword_search(
    vault_path: str,
    query: str,
    top_k: int = 3,
    token_budget: int = 800,
    exclude_deprecated: bool = True,
    allowed_packs: list[str] | None = None,
) -> list[VaultChunk]:
    """Keyword-based vault search.

    Scores notes by term overlap × retrieval_weight. Applies a character
    budget (~4 chars per token) when truncating chunk content. Never raises.

    When allowed_packs is set (non-empty list), only notes whose inferred pack
    is in effective_packs are returned. SYSTEM pack is always included.
    Unclassified notes (pack=None) always pass the filter for backward compat.
    """
    effective_packs: frozenset[str] | None = None
    if allowed_packs:
        effective_packs = frozenset(p.upper() for p in allowed_packs) | {"SYSTEM"}

    vault_root = Path(vault_path)
    query_terms = set(query.lower().split())
    scored: list[tuple[float, VaultNote]] = []

    for p in list_markdown_notes(vault_path):
        note = read_note(p, vault_root=vault_root)
        if note is None:
            continue
        if exclude_deprecated and note.status.lower() == "deprecated":
            continue

        # Pack filter: skip notes with a known pack that is not in effective_packs.
        # Unclassified notes (pack=None) always pass.
        if effective_packs is not None and note.pack is not None:
            if note.pack not in effective_packs:
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
                pack=note.pack,
            )
        )

        if char_budget <= 0:
            break

    return chunks
