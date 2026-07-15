# Mission Inbox / Preview Index v0

Status: v0 (read-only index). PR #271. Scans a folder of preview *bundles*
(`*.preview-bundle.json`, #269) and builds an auditable index of dry-run previews (#268).

    python -m assistant_os.mso.mission_inbox_index docs/mission/inbox

> inbox ≠ real queue · index ≠ execution · preview ≠ dispatch · valid bundle ≠ authorization ·
> stdout JSON is review/simulation evidence, not execution proof.

## Module
`assistant_os/mso/mission_inbox_index.py` — stdlib + sibling contracts. No execution,
dispatch, model/API calls, Runner, real queue/scheduler, endpoint, token minting, authority,
UI, backend deploy, or **file writes/moves/renames/deletes**. Nothing is marked processed.
`can_execute`/`can_dispatch` are always `False`.

## API
- `scan_inbox(path) -> MissionInboxIndex` — fail-closed on a bad path; deterministic
  (lexicographic filename order); read-only.
- `scan_bundle_file(path) -> InboxPreviewRecord` — per-file; never raises for content.
- `index_to_dict(index)` / `normalize_index_to_json(index)` — deterministic JSON.
- `main(argv)` — read-only CLI: prints index JSON (exit 0, even if some bundles invalid) or
  `{ok:false, errors, can_execute:false, can_dispatch:false}` (exit 1) for a bad path. Never writes.

## File selection
Only `*.preview-bundle.json` files are treated as bundles. Any other file (incl. plain
`*.json`, `*.txt`) is recorded as `SKIPPED_UNSUPPORTED_FILE` — never executed.

`InboxRecordStatus`: VALID_PREVIEW, INVALID_BUNDLE, NO_ELIGIBLE_WORKER, BLOCKED,
NEEDS_HUMAN_REVIEW, SKIPPED_UNSUPPORTED_FILE, ERROR.

## Safety invariants
1. Bad inbox path ⇒ fail closed. 2/3. can_execute/can_dispatch always false (index + records).
4. Not a real queue. 5. Not a Runner. 6. No authority. 7. Valid record ⇏ execution. 8. Valid preview ⇏
real handoff. 9. Invalid bundles are marked invalid, never break the index. 10. Invalid worker not eligible.
11. Empty workers ⇒ NO_ELIGIBLE_WORKER (no unsafe fallback). 12. Secret-like content ⇒ INVALID_BUNDLE
(value never leaked). 13. Unsupported files ⇒ SKIPPED, never executed. 14. Unknown fields strict by default,
`--allow-unknown` opt-in. 15. Refs, not raw contents. 16. Stable JSON. 17. Deterministic by filename.
18. No writes. 19. No network/model calls. 20. No token minting.

## Future connection
Feeds a future **read-only UI / mission console**: a human browses the indexed previews (and their
DRAFT handoff envelopes) before any future governed dispatch — which stays outside this module.

## Out of scope (explicitly)
No Runner, dispatch, execution, real queue/scheduler, UI execute, endpoint, backend deploy, external API,
model calls, capability token, authority, file writes/moves.
