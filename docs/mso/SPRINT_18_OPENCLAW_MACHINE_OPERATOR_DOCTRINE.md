# Sprint 18: OpenClaw MACHINE_OPERATOR Doctrine

## Objective

Freeze the insertion doctrine for OpenClaw without changing MSO behavior or
HOST behavior.

This sprint originally defined architecture and contracts only. The current
repository now includes bounded live Tier A execution behind the same doctrine;
Linux-side trust verification and backend hardening remain out of scope here.

## Doctrine

- OpenClaw is a **MACHINE_OPERATOR** executor.
- HOST remains native and deterministic.
- MACHINE_OPERATOR is a separate lane, not a HOST extension.
- The MSO remains sovereign and does not execute actions directly.
- The adapter is a translation boundary, not a second decision-maker.
- OpenClaw is bounded, subordinate, and non-sovereign.

Core rule:

> **The adapter translates; the MSO decides; OpenClaw executes; nobody crosses lanes.**

## Why OpenClaw is MACHINE_OPERATOR

OpenClaw represents delegated machine-side execution, not local HOST authority.
Its correct architectural role is therefore a subordinate execution arm that receives structured intent after sovereign decision-making has already happened.

This preserves the existing control model already established in the repository:

- the orchestrator remains the canonical execution entrypoint
- the kernel remains the authority for validation and issuance
- the MSO remains sovereign governance, not execution
- subordinate executors operate only through explicit contracts

## Why OpenClaw is not HOST

HOST in this repository is the native deterministic lane for local machine actions.
Treating OpenClaw as HOST would blur sovereignty, backend translation, and execution authority into one path.

That would violate the current boundary discipline:

- HOST would stop being a native deterministic lane
- backend-specific behavior would leak into sovereign-facing contracts
- translation and execution concerns would be mixed
- future replacement of the machine operator backend would become harder

For this insertion line, the authoritative architecture is:

- HOST = native deterministic machine access
- MACHINE_OPERATOR = delegated subordinate machine execution

## Control plane vs execution plane

The control plane remains above the execution plane.

- **Control plane**
  - MSO interpretation
  - policy/governance decisions
  - approval requirements
  - contract issuance
  - audit correlation

- **Execution plane**
  - adapter translation into a backend-specific envelope
  - bounded execution by OpenClaw
  - observation/evidence return
  - declared side-effect reporting

The control plane must never inherit backend wire semantics.
The execution plane must never acquire sovereign authority.

## Contract rule

The sovereign side speaks through an implementation-independent MACHINE_OPERATOR contract.
That contract must be stable even if OpenClaw is replaced later by another machine operator backend.

Therefore:

- no OpenClaw wire fields in the sovereign contract
- no browser protocol details in the sovereign contract
- no gateway transport assumptions in the sovereign contract
- no implicit approvals
- no cross-lane escalation by execution code

## Out of scope in this sprint

This sprint note still does **not** imply:

- Linux-side auth validation
- mTLS / PKI / backend attestation
- secret-enabled MACHINE_OPERATOR execution
- HOST integration changes
- MSO redesign
- a broader multi-agent roadmap
