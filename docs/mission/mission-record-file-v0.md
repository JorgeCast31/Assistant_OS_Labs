# Mission Record File / Validator v0

Status: v0 (file format + loader + validator only). PR #263. Continues **TASK-0001 F1**:
authorization must be able to exist as a versioned, reviewable, validatable **file** —
not a chat message (human-cable).

## Purpose

Let a `MissionAuthorizationRecord` (PR #262) be stored as a JSON file and be loaded,
validated and normalized deterministically by humans, reviewers, or CI.

## Module

`assistant_os/mso/mission_record_io.py` — stdlib only; imports only the #262 contract.

- `load_record_from_dict(data, *, strict_unknown=True)`
- `load_record_from_json(text, *, strict_unknown=True)`
- `load_record_from_path(path, *, strict_unknown=True)`
- `normalize_to_json(record)` → deterministic (sorted keys)
- `validate_source(source)` → `{ok, errors, warnings, record_id, can_execute, is_active, normalized}` (never raises)
- `main(argv)` → read-only CLI, exit `0` (valid) / `1` (invalid)

## File format

A single JSON object with the contract fields (see
`mission-authorization-record-v0-contract.md`). `execution_policy` should be
`NO_EXECUTION` unless a later governed path is explicitly intended. Example:
`docs/mission/examples/mission-record.draft.example.json` (fictitious `DRAFT`).

## How to validate

```
python -m assistant_os.mso.mission_record_io docs/mission/examples/mission-record.draft.example.json
```
Exit code `0` = valid, `1` = invalid. The CLI never writes files, never executes,
and never prints secret values.

## What a record means — and does NOT mean

- **record exists ≠ can execute.** A file on disk grants nothing.
- **approved ≠ executed.** `HUMAN_APPROVED` marks human sign-off, not an operational permit.
- **validator ≠ runner.** Loading/validating runs nothing; `can_execute` stays `False`.
- Authority to execute is a *separate, later, governed* step — never this file.

## Anti-secret rules

- A record must not contain secrets. Secret-like content (API keys, tokens,
  `authorization:` headers, long hex blobs, etc.) **invalidates** the record.
- Loader/validator error messages name fields/keys only — never echo values.
  JSON parse errors report position/reason, never the document body.

## Suggested future location for real records

Real, human-authored records should live in a **reviewed, versioned** path (e.g.
`coordination/missions/` under normal PR review), never auto-written by the backend
and never under an "active/executable" runtime path. v0 ships only the format,
loader, validator and a docs example — no runtime record creation.

## Out of scope (explicitly)

No Runner, no execution, no UI execute, no creation endpoint, no backend deploy,
no queue/scheduler, no token minting, no authority inference, no backend-written
runtime records.
