import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type {
  PreparedActionsQueueResponse,
  PreparedActionQueueEntry,
  ConfirmPreparedActionResult,
  MSOPolicyReviewResult,
  MSOAuthorityBindingResult,
  OperationTraceV0,
} from '@/lib/types'

// ── Mock API helpers ──────────────────────────────────────────────────────────
vi.mock('@/lib/api', () => ({
  getPreparedActionsPending: vi.fn(),
  confirmPreparedAction: vi.fn(),
  triggerPolicyReview: vi.fn(),
  triggerAuthorityBinding: vi.fn(),
}))

import {
  getPreparedActionsPending,
  confirmPreparedAction,
  triggerPolicyReview,
  triggerAuthorityBinding,
} from '@/lib/api'
import { PreparedActionsReviewPanel } from '../PreparedActionsReviewPanel'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const NOW = '2026-05-30T00:00:00.000Z'

const TRACE_PENDING: OperationTraceV0 = {
  trace_version: 'v0',
  entry_id: 'qe-test-001',
  action_id: 'cpa-test-001',
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',     description: 'CODE: code_review', completed: true },
    { step: 'human_confirmation', status: 'pending',  label: 'Human Confirmation',  description: 'Awaiting operator confirmation.', completed: false },
    { step: 'policy_review',      status: 'missing',  label: 'Policy Review',       description: 'Not yet reached.', completed: false },
    { step: 'authority_binding',  status: 'missing',  label: 'Authority Binding Draft', description: 'Not yet reached.', completed: false },
    { step: 'police_readiness',   status: 'not_ready', label: 'Police Readiness',   description: 'Authority chain prerequisites not yet met.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',  description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['human_confirmation', 'policy_review'],
  blocking_reasons: [],
  next_safe_step: 'POST /mso/prepared-actions/confirm',
  execution_allowed: false,
  can_execute_now: false,
  used_execution: false,
}

const TRACE_CONFIRMED: OperationTraceV0 = {
  ...TRACE_PENDING,
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',     description: 'CODE: code_review', completed: true },
    { step: 'human_confirmation', status: 'complete', label: 'Human Confirmation',  description: 'Operator confirmed.', completed: true },
    { step: 'policy_review',      status: 'pending',  label: 'Policy Review',       description: 'Awaiting capability policy evaluation.', completed: false },
    { step: 'authority_binding',  status: 'missing',  label: 'Authority Binding Draft', description: 'Not yet reached.', completed: false },
    { step: 'police_readiness',   status: 'not_ready', label: 'Police Readiness',   description: 'Authority chain prerequisites not yet met.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',  description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['policy_review'],
  next_safe_step: 'POST /mso/prepared-actions/policy-review',
}

const TRACE_POLICY_APPROVED: OperationTraceV0 = {
  ...TRACE_PENDING,
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',     description: 'CODE: code_review', completed: true },
    { step: 'human_confirmation', status: 'complete', label: 'Human Confirmation',  description: 'Operator confirmed.', completed: true },
    { step: 'policy_review',      status: 'complete', label: 'Policy Review',       description: 'Capability policy approved (outcome=approved).', completed: true },
    { step: 'authority_binding',  status: 'pending',  label: 'Authority Binding Draft', description: 'Awaiting authority binding draft creation.', completed: false },
    { step: 'police_readiness',   status: 'not_ready', label: 'Police Readiness',   description: 'Authority chain prerequisites not yet met.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',  description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['authority_binding_draft'],
  next_safe_step: 'POST /mso/prepared-actions/authority-binding',
}

const TRACE_POLICY_DENIED: OperationTraceV0 = {
  ...TRACE_PENDING,
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',     description: 'CODE: code_review', completed: true },
    { step: 'human_confirmation', status: 'complete', label: 'Human Confirmation',  description: 'Operator confirmed.', completed: true },
    { step: 'policy_review',      status: 'denied',   label: 'Policy Review',       description: 'Policy denied by capability registry.', completed: false },
    { step: 'authority_binding',  status: 'missing',  label: 'Authority Binding Draft', description: 'Not yet reached.', completed: false },
    { step: 'police_readiness',   status: 'blocked',  label: 'Police Readiness',    description: 'Authority chain blocked.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',  description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: [],
  blocking_reasons: ['Policy denied'],
  next_safe_step: 'Policy was denied.',
}

const TRACE_BINDING_COMPLETE: OperationTraceV0 = {
  ...TRACE_PENDING,
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',     description: 'CODE: code_review', completed: true },
    { step: 'human_confirmation', status: 'complete', label: 'Human Confirmation',  description: 'Operator confirmed.', completed: true },
    { step: 'policy_review',      status: 'complete', label: 'Policy Review',       description: 'Capability policy approved.', completed: true },
    { step: 'authority_binding',  status: 'complete', label: 'Authority Binding Draft', description: 'MSOAuthorityBindingDraft created.', completed: true },
    { step: 'police_readiness',   status: 'draft_complete', label: 'Police Readiness', description: 'MSO draft chain complete.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',  description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['CapabilityToken', 'OperationBinding', 'AuthorizedPlan', 'PoliceGate', 'Runner'],
  next_safe_step: 'Authority chain draft is complete.',
}

function makeEntry(overrides: Partial<PreparedActionQueueEntry> = {}): PreparedActionQueueEntry {
  return {
    artifact_type: 'confirmable_prepared_action_queue_entry',
    queue_entry_id: 'qe-test-001',
    prepared_action_id: 'cpa-test-001',
    preparation_id: 'prep-test-001',
    proposal_id: 'prop-test-001',
    user_intent: 'Review the pending plan for CODE domain',
    domain: 'CODE',
    requested_action: 'code_review',
    capability_name: 'code_review_capability',
    capability_scope: ['read', 'suggest'],
    delegated_seat_ref: null,
    provider_name: null,
    model_name: null,
    human_confirmation_status: 'pending',
    status: 'pending_review',
    created_at: NOW,
    review_only: true,
    execution_allowed: false,
    can_execute_now: false,
    notes: 'Manual review queue entry for domain=CODE',
    ...overrides,
  }
}

function makeQueueResponse(items: PreparedActionQueueEntry[]): PreparedActionsQueueResponse {
  return {
    ok: true,
    source: 'prepared_action_queue',
    count: items.length,
    items,
    review_only: true,
    execution_allowed: false,
    can_execute_now: false,
    note: 'Prepared action review queue is read-only.',
  }
}

const EMPTY_QUEUE: PreparedActionsQueueResponse = makeQueueResponse([])

const UNAVAILABLE_QUEUE: PreparedActionsQueueResponse = {
  ok: false,
  source: 'prepared_action_queue',
  count: 0,
  items: [],
  review_only: true,
  execution_allowed: false,
  can_execute_now: false,
  note: 'Prepared action review queue is read-only.',
  error: 'Prepared actions backend unavailable',
}

const CONFIRM_OK: ConfirmPreparedActionResult = {
  ok: true,
  entry_id: 'qe-test-001',
  action_id: 'cpa-test-001',
  human_confirmation_status: 'human_confirmed',
  execution_allowed: false,
  can_execute_now: false,
  recorded_at: NOW,
  note: 'Human confirmation recorded. No execution authority granted.',
}

const POLICY_REVIEW_OK: MSOPolicyReviewResult = {
  ok: true,
  entry_id: 'qe-test-001',
  action_id: 'cpa-test-001',
  policy_review_id: 'prd-test-001',
  policy_outcome: 'approved',
  capability_mode: 'allow',
  execution_allowed: false,
  can_execute_now: false,
  used_execution: false,
  note: 'Policy decision draft recorded. Execution remains closed.',
}

const AUTHORITY_BINDING_OK: MSOAuthorityBindingResult = {
  ok: true,
  entry_id: 'qe-test-001',
  action_id: 'cpa-test-001',
  policy_review_id: 'prd-test-001',
  authority_binding_id: 'ab-test-001',
  binding_status: 'drafted',
  requires_authorized_plan: true,
  requires_police_gate: true,
  execution_allowed: false,
  can_execute_now: false,
  used_execution: false,
  note: 'Authority binding draft recorded. AuthorizedPlan, PoliceGate, and execution still required.',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getPreparedActionsPending).mockResolvedValue(EMPTY_QUEUE)
  vi.mocked(confirmPreparedAction).mockResolvedValue(CONFIRM_OK)
  vi.mocked(triggerPolicyReview).mockResolvedValue(POLICY_REVIEW_OK)
  vi.mocked(triggerAuthorityBinding).mockResolvedValue(AUTHORITY_BINDING_OK)
  vi.stubGlobal('confirm', () => true)
})

// ── 1. Empty state ────────────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — empty state', () => {
  it('renders "No prepared actions pending" when queue is empty', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(EMPTY_QUEUE)
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/no prepared actions pending/i)).toBeInTheDocument()
    )
  })
})

// ── 2. Load pending actions ───────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — loading', () => {
  it('calls getPreparedActionsPending on mount', async () => {
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => expect(getPreparedActionsPending).toHaveBeenCalled())
  })
})

// ── 3. Renders prepared_action_id ────────────────────────────────────────────

describe('PreparedActionsReviewPanel — entry display', () => {
  it('renders prepared_action_id', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/cpa-test-001/)).toBeInTheDocument()
    )
  })

  it('renders preparation_id as correlation context when present', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/prep-test-001/)).toBeInTheDocument()
    )
  })

  it('renders "Prepared — Awaiting Confirmation" label', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/Prepared — Awaiting Confirmation/)).toBeInTheDocument()
    )
  })

  it('renders domain and requested_action from entry', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => {
      expect(document.body.textContent).toContain('CODE')
      expect(document.body.textContent).toContain('code_review')
    })
  })

  it('shows Confirm button for pending_review entries', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /confirm preparedaction/i })).toBeInTheDocument()
    )
  })
})

// ── operation_trace_v0 rendering ──────────────────────────────────────────────

describe('PreparedActionsReviewPanel — operation_trace_v0', () => {
  it('renders operation_trace_v0 steps when present', async () => {
    const entry = makeEntry({ operation_trace_v0: TRACE_PENDING })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => {
      expect(screen.getByText(/Prepared Action/)).toBeInTheDocument()
      expect(screen.getByText(/Human Confirmation/)).toBeInTheDocument()
      expect(screen.getByText(/Policy Review/)).toBeInTheDocument()
      expect(screen.getByText(/Authority Binding Draft/)).toBeInTheDocument()
      expect(screen.getByText(/Police Readiness/)).toBeInTheDocument()
      expect(screen.getByText(/Execution/)).toBeInTheDocument()
    })
  })

  it('renders step labels from operation_trace_v0', async () => {
    const entry = makeEntry({ operation_trace_v0: TRACE_PENDING })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(document.body.textContent).toContain('Prepared Action')
    )
  })

  it('renders next_safe_step from operation_trace_v0', async () => {
    const entry = makeEntry({ operation_trace_v0: TRACE_PENDING })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(document.body.textContent).toContain('/mso/prepared-actions/confirm')
    )
  })
})

// ── Evaluate Policy button ────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — Evaluate Policy', () => {
  it('shows "Evaluate Policy" button when human_confirmed and no policy_review_id', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      operation_trace_v0: TRACE_CONFIRMED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /evaluate policy/i })).toBeInTheDocument()
    )
  })

  it('does NOT show "Evaluate Policy" when policy_review_id already exists', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-existing',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /evaluate policy/i })).toBeNull()
  })

  it('does NOT show "Evaluate Policy" for pending (unconfirmed) entries', async () => {
    const entry = makeEntry({ human_confirmation_status: 'pending' })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /evaluate policy/i })).toBeNull()
  })

  it('"Evaluate Policy" requires window.confirm()', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const entry = makeEntry({ human_confirmation_status: 'human_confirmed', operation_trace_v0: TRACE_CONFIRMED })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /evaluate policy/i }))
    fireEvent.click(screen.getByRole('button', { name: /evaluate policy/i }))
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled())
  })

  it('"Evaluate Policy" does not call triggerPolicyReview if window.confirm() returns false', async () => {
    vi.stubGlobal('confirm', () => false)
    const entry = makeEntry({ human_confirmation_status: 'human_confirmed', operation_trace_v0: TRACE_CONFIRMED })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /evaluate policy/i }))
    fireEvent.click(screen.getByRole('button', { name: /evaluate policy/i }))
    await waitFor(() => expect(triggerPolicyReview).not.toHaveBeenCalled())
  })

  it('"Evaluate Policy" calls triggerPolicyReview with correct payload', async () => {
    const entry = makeEntry({ human_confirmation_status: 'human_confirmed', operation_trace_v0: TRACE_CONFIRMED })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /evaluate policy/i }))
    fireEvent.click(screen.getByRole('button', { name: /evaluate policy/i }))
    await waitFor(() =>
      expect(triggerPolicyReview).toHaveBeenCalledWith({
        entry_id: 'qe-test-001',
        action_id: 'cpa-test-001',
      })
    )
  })

  it('refreshes queue after triggering policy review', async () => {
    const entry = makeEntry({ human_confirmation_status: 'human_confirmed', operation_trace_v0: TRACE_CONFIRMED })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /evaluate policy/i }))
    fireEvent.click(screen.getByRole('button', { name: /evaluate policy/i }))
    await waitFor(() => expect(getPreparedActionsPending).toHaveBeenCalledTimes(2))
  })
})

// ── Create Authority Binding Draft button ─────────────────────────────────────

describe('PreparedActionsReviewPanel — Create Authority Binding Draft', () => {
  it('shows "Create Authority Binding Draft" when policy approved and no binding_id', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /create authority binding draft/i })).toBeInTheDocument()
    )
  })

  it('shows "Create Authority Binding Draft" when policy_outcome is approved_confirm_only', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved_confirm_only',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /create authority binding draft/i })).toBeInTheDocument()
    )
  })

  it('does NOT show "Create Authority Binding Draft" when policy denied', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'denied',
      operation_trace_v0: TRACE_POLICY_DENIED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /create authority binding draft/i })).toBeNull()
  })

  it('does NOT show "Create Authority Binding Draft" when binding already exists', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      authority_binding_id: 'ab-existing',
      operation_trace_v0: TRACE_BINDING_COMPLETE,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /create authority binding draft/i })).toBeNull()
  })

  it('"Create Authority Binding Draft" requires window.confirm()', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /create authority binding draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /create authority binding draft/i }))
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled())
  })

  it('"Create Authority Binding Draft" does not call triggerAuthorityBinding if window.confirm() returns false', async () => {
    vi.stubGlobal('confirm', () => false)
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /create authority binding draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /create authority binding draft/i }))
    await waitFor(() => expect(triggerAuthorityBinding).not.toHaveBeenCalled())
  })

  it('"Create Authority Binding Draft" calls triggerAuthorityBinding with correct payload', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /create authority binding draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /create authority binding draft/i }))
    await waitFor(() =>
      expect(triggerAuthorityBinding).toHaveBeenCalledWith({
        entry_id: 'qe-test-001',
        action_id: 'cpa-test-001',
      })
    )
  })

  it('refreshes queue after creating authority binding draft', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /create authority binding draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /create authority binding draft/i }))
    await waitFor(() => expect(getPreparedActionsPending).toHaveBeenCalledTimes(2))
  })
})

// ── police_readiness summary ──────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — police_readiness', () => {
  it('shows police_readiness.readiness_status if present', async () => {
    const entry = makeEntry({
      police_readiness: {
        readiness_status: 'awaiting_human_confirmation',
        current_chain_stage: 'human_confirmation',
        missing_requirements: ['human_confirmation'],
        blocking_reasons: [],
        next_safe_step: 'POST /mso/prepared-actions/confirm',
        execution_allowed: false,
        can_execute_now: false,
        used_execution: false,
      },
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(document.body.textContent).toContain('awaiting_human_confirmation')
    )
  })
})

// ── Confirm flow (existing tests) ─────────────────────────────────────────────

describe('PreparedActionsReviewPanel — confirm flow', () => {
  it('calls window.confirm() before calling confirmPreparedAction', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /confirm preparedaction/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm preparedaction/i }))
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled())
  })

  it('does not call confirmPreparedAction if window.confirm() returns false', async () => {
    vi.stubGlobal('confirm', () => false)
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /confirm preparedaction/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm preparedaction/i }))
    await waitFor(() => expect(confirmPreparedAction).not.toHaveBeenCalled())
  })

  it('calls confirmPreparedAction with correct payload', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /confirm preparedaction/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm preparedaction/i }))
    await waitFor(() =>
      expect(confirmPreparedAction).toHaveBeenCalledWith(
        expect.objectContaining({
          entry_id: 'qe-test-001',
          action_id: 'cpa-test-001',
          confirmed: true,
        }),
      )
    )
  })

  it('calls getPreparedActionsPending again after confirming', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /confirm preparedaction/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm preparedaction/i }))
    await waitFor(() => expect(getPreparedActionsPending).toHaveBeenCalledTimes(2))
  })
})

// ── Error state ───────────────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — error state', () => {
  it('shows error state when backend unavailable', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(UNAVAILABLE_QUEUE)
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument()
    )
  })

  it('shows error when policy review returns failure', async () => {
    vi.mocked(triggerPolicyReview).mockResolvedValue({
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: 'Policy evaluation service unavailable',
    })
    const entry = makeEntry({ human_confirmation_status: 'human_confirmed', operation_trace_v0: TRACE_CONFIRMED })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /evaluate policy/i }))
    fireEvent.click(screen.getByRole('button', { name: /evaluate policy/i }))
    await waitFor(() =>
      expect(screen.getByText(/Policy evaluation service unavailable/)).toBeInTheDocument()
    )
  })

  it('shows error when authority binding returns failure', async () => {
    vi.mocked(triggerAuthorityBinding).mockResolvedValue({
      ok: false,
      execution_allowed: false,
      can_execute_now: false,
      error: 'Authority binding service unavailable',
    })
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /create authority binding draft/i }))
    fireEvent.click(screen.getByRole('button', { name: /create authority binding draft/i }))
    await waitFor(() =>
      expect(screen.getByText(/Authority binding service unavailable/)).toBeInTheDocument()
    )
  })

  it('shows "Loading prepared actions…" on initial fetch', async () => {
    let resolve: (v: typeof EMPTY_QUEUE) => void
    vi.mocked(getPreparedActionsPending).mockReturnValue(new Promise(r => { resolve = r }))
    render(<PreparedActionsReviewPanel />)
    expect(screen.getByText(/Loading prepared actions/)).toBeInTheDocument()
    resolve!(EMPTY_QUEUE)
  })
})

// ── Forbidden controls ────────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — forbidden controls', () => {
  it('never renders an Execute button', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /^execute$/i })).toBeNull()
  })

  it('never renders forbidden labels', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      authority_binding_id: 'ab-test-001',
      operation_trace_v0: TRACE_BINDING_COMPLETE,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    const FORBIDDEN = [
      /\bExecute\b/,
      /\bRun\b/,
      /ready to execute/i,
      /\bRunning\b/,
      /\bLive\b/,
      /\bCompleted\b/,
    ]
    for (const pattern of FORBIDDEN) {
      expect(document.body.textContent).not.toMatch(pattern)
    }
  })

  it('policy approved does not appear as execution authorization', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      operation_trace_v0: TRACE_POLICY_APPROVED,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(document.body.textContent).not.toMatch(/ready to execute/i)
    expect(document.body.textContent).not.toMatch(/\bAuthorized\b/)
  })

  it('authority binding draft does not appear as token or execution authority', async () => {
    const entry = makeEntry({
      human_confirmation_status: 'human_confirmed',
      policy_review_id: 'prd-test-001',
      policy_outcome: 'approved',
      authority_binding_id: 'ab-test-001',
      operation_trace_v0: TRACE_BINDING_COMPLETE,
    })
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([entry]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(document.body.textContent).not.toMatch(/CapabilityToken/i)
    expect(document.body.textContent).not.toMatch(/execution authority/i)
    expect(document.body.textContent).not.toMatch(/\bRunning\b/)
  })
})

// ── Export ────────────────────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — export', () => {
  it('is exported as a named component', () => {
    expect(PreparedActionsReviewPanel).toBeDefined()
    expect(typeof PreparedActionsReviewPanel).toBe('function')
  })
})
