# SovereignStateStore Interface Snapshot v1

## Method

is_execution_allowed(query)

## Required Query Fields

- approval_id: string
- capability_name: string
- capability_scope: string
- expires_at: string
- policy_decision_ref: string
- governance_ref: string

## Expected Outputs

- allowed
  - state: allowed
  - allowed: true
  - reason.code: allowed

- blocked
  - state: blocked
  - allowed: false
  - reason.code: one of
    - kill_switch_active
    - restriction_active
    - approval_missing
    - approval_expired
    - governance_missing
    - governance_unresolved
    - state_unavailable

## Fail-Closed Rule

When sovereign state cannot be read or determined with certainty, output must be blocked (allowed=false) with reason.code=state_unavailable.
