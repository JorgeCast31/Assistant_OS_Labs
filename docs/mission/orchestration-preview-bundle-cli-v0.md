# Orchestration Preview Bundle / CLI v0

Status: v0 (read-only IO + CLI). PR #269. Builds an `OrchestrationPreview` (#268) from a JSON
*bundle* (a delegation packet + candidate worker profiles).

    python -m assistant_os.mso.orchestration_preview_io docs/mission/examples/orchestration-preview-bundle.example.json

> bundle ≠ authorization · CLI preview ≠ execution · preview ≠ dispatch ·
> generated handoff envelope ≠ real handoff · stdout JSON is simulation evidence, not execution proof.

## Module
`assistant_os/mso/orchestration_preview_io.py` — stdlib + sibling contracts. No execution,
dispatch, model calls, external APIs, Runner, queue, endpoint, token minting, authority, or
**file writes**. Output only to stdout/stderr.

## API
- `load_bundle_from_dict/json/path(...)` — fail-closed (`OrchestrationBundleError`); unknown fields
  rejected by default; raw scan rejects secret-like or oversized (>4096) strings by path (never value).
- `build_preview_from_bundle(bundle) -> OrchestrationPreview` — invalid packet ⇒ INVALID_INPUT;
  unconstructable/invalid workers ⇒ excluded (never eligible); never mutates the bundle.
- `validate_bundle_source(source) -> {ok, errors, warnings, preview, can_dispatch:false, can_execute:false}` (never raises).
- `normalize_preview_to_json(preview)` — deterministic.
- `main(argv)` — read-only CLI: prints normalized preview JSON (exit 0) or `{ok:false, errors, can_execute:false, can_dispatch:false}` (exit 1). Never writes files.

## `OrchestrationPreviewBundle`
`bundle_id, delegation_packet (obj), workers (list), created_at, created_by, requested_preview_id, audit_notes`.

## Safety invariants
1. Invalid ⇒ fail closed. 2/3. can_execute/can_dispatch always false. 4. Bundle ≠ authorization. 5. ≠ real handoff.
6. CLI runs no mission. 7. No side effects. 8. No filesystem writes. 9. No network. 10. No model calls.
11. No token minting. 12. Empty workers ⇒ NO_ELIGIBLE_WORKER (no unsafe fallback). 13. Invalid worker not eligible.
14. Invalid packet ⇒ INVALID_INPUT. 15. Unknown fields fail closed by default. 16. `--allow-unknown` ⇒ warning.
17. No secrets in bundle/errors/warnings/blockers/audit_notes/stdout. 18. Refs, not raw contents. 19. Stable JSON. 20. Deterministic.

## Future connection
Feeds a future **read-only UI / mission inbox**: a human loads a bundle, reviews the resulting preview
(and its DRAFT handoff envelope), before any future governed dispatch — which stays outside this module.

## Out of scope (explicitly)
No Runner, dispatch, execution, queue/scheduler, UI execute, endpoint, backend deploy, external API,
model calls, capability token, authority, file writes.
