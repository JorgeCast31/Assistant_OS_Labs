# Police Token Gate Contract

## Purpose

The token-bound Police gate is the future execution boundary for Police decisions. It will decide whether a specific execution instance may proceed after validating the token, operation binding, plan binding, capability scope, and temporal restrictions that apply to that instance.

Police owns both declarative evaluation and token-bound gate contracts because both are enforcement-facing Police concepts. The boundary is separated by file and layer inside `assistant_os/police/`, not by moving the future gate contract into a different package.

S-POLICE-CORE-02 adds only the contract and a dry integration harness. It does not implement token verification, token consumption, runner enforcement, sandbox enforcement, or real pipeline wiring.

## Source Of Truth

For this work, the source-of-truth hierarchy is:

1. Current code in `assistant_os/` and `ui/`.
2. `README.md`, `docs/RUNTIME_TOPOLOGY.md`, and `docs/CHAT.md`.
3. `docs/security/`, `docs/operability/`, and `docs/observability/`.
4. `docs/brains/` and `contracts/line-f/` as historical or conceptual specs.
5. `archive/` as historical reference only.

## Evaluation Versus Decision

`PoliceEvaluation` is the Police v0 declarative pre-evaluation result. It describes whether a request appears allowed, denied, or in need of confirmation based on declared permissions and risk signals. V0 files must not import, alias, construct, or otherwise depend on the future gate contract.

`PoliceDecision` is the future token-bound execution-gate result. It is intentionally separate from `PoliceEvaluation` and does not reuse the v0 tool or environment allow/deny lists. It must not be used by Police v0.

`PoliceEvaluation.ALLOW` is not execution authorization. It must never be treated as permission to run work.

`PoliceOutcome.PERMITTED` will eventually mean that a specific token-bound execution instance passed enforcement. The gate outcome values are deliberately `permitted`, `denied`, and `deferred` so they are structurally distinct from `PoliceEvaluationType`.

## Current Contract

Layer separation:

- `models.py`, `enforcer.py`, and `audit.py` remain Police v0 declarative evaluation files.
- `gate_models.py`, `enforcement.py`, and `harness.py` are the future token-bound gate layer.
- `__init__.py` exports Police v0 only. It must not mention or export gate types, `enforcement`, `harness`, `check`, or `apply_police_gate`.

`PoliceGateRequest` carries refs only:

- `token_ref`
- `binding_ref`
- `authorized_plan_ref`
- governance, policy, trace, operation, capability, and active restriction refs

It does not import or hold token, capability, binding, plan, sandbox, runner, or pipeline objects.

`PoliceDecision` is frozen. Its `permitted` flag is valid only when `outcome == PoliceOutcome.PERMITTED`; denied and deferred outcomes are never permitted.

## Intentionally Unimplemented

`assistant_os.police.enforcement.check` raises `NotImplementedError` until S-POLICE-CORE-03.

This is deliberate. S-POLICE-CORE-02 must not implement:

- token validity checks
- token consumption
- `OperationBinding`
- `AuthorizedPlan` binding
- temporal restriction enforcement
- runner or sandbox boundary enforcement
- HTTP, UI, CODE, or real pipeline integration

## Dry Harness

`apply_police_gate` maps a `PoliceDecision` into a non-executable result:

- `PERMITTED` with `permitted=True` returns `would_continue`.
- `DENIED` returns `blocked` with `why_blocked`.
- `DEFERRED` returns `requires_confirmation` with the confirmation reason.

The harness does not call enforcement, pipelines, runners, CODE, missions, sandbox, or token verification. It is a dry harness only and is not a production path.

## S-POLICE-CORE-03 Scope

The next sprint will implement:

- token validity
- `OperationBinding`
- `AuthorizedPlan` binding
- token consumption
- temporal restrictions
- runner and sandbox boundary behavior

## Future Wiring Order

1. CODE pipeline co-enforcement
2. runner boundary
3. agent registry enforcement
4. mission execution dry-run

## NO-GO Boundaries

Until the gate implementation sprint, do not wire this contract into real runtime paths. Do not modify the CODE pipeline, runners, sandbox, webhook server, UI, missions, or policy/MSO authority modules for this contract-only phase.
