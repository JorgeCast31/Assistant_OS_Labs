# docs/atlas — Navigational Atlas

**docs/atlas is navigational memory, not runtime state.**

It exists so human operators and Obsidian can navigate the system without touching live code or contracts. Nothing here is executed. Nothing here is authoritative.

## Purpose

- Orient new operators to system topology
- Surface which layers are closed vs. pending
- Link directly to active contracts and tests (the real source of truth)

## What this is NOT

- Not a source of truth (code and tests are)
- Not a runtime artefact (nothing reads these files at execution time)
- Not a substitute for reading contracts

## Source-of-Truth Hierarchy

| Priority | Source | Why |
|---|---|---|
| 1 | `tests/` — passing tests | Executable proof of behaviour |
| 2 | Active contracts in `docs/mission/`, `docs/police/`, `docs/agents/` | Signed interface definitions |
| 3 | `docs/atlas/` maps (this folder) | Navigational memory only |
| 4 | `archive/` | Historical references — may be stale |
| 5 | `.obsidian/` | **Never canonical. Local workspace config only.** |

## Maps in this Atlas

| File | Covers |
|---|---|
| [SYSTEM_MAP.md](SYSTEM_MAP.md) | Overall system layers and closure status |
| [AUTHORITY_MAP.md](AUTHORITY_MAP.md) | Authority chain: MSO → Policy → Police → Agents |
| [POLICE_MAP.md](POLICE_MAP.md) | Police evaluation and decision layers |
| [MISSION_MAP.md](MISSION_MAP.md) | Mission lifecycle and seam architecture |
| [AGENTS_MAP.md](AGENTS_MAP.md) | Agent permission bridge |
| [EXECUTION_CHANNELS_MAP.md](EXECUTION_CHANNELS_MAP.md) | Execution candidate pipeline |
| [PERSISTENCE_MAP.md](PERSISTENCE_MAP.md) | Persistence boundaries and state ownership |
| [ROADMAP_ALPHA.md](ROADMAP_ALPHA.md) | Alpha-phase pending layers |
