import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { PlanStatusIndicator } from '../PlanStatusIndicator'
import type { PlanPrepareStatusResponse } from '@/lib/types'

// ── Mock API helpers ──────────────────────────────────────────────────────────
vi.mock('@/lib/api', () => ({
  getPlanPrepareStatus: vi.fn(),
  ackPlan: vi.fn(),
  preparePlan: vi.fn(),
}))

import { getPlanPrepareStatus, ackPlan, preparePlan } from '@/lib/api'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeStatus(
  status: PlanPrepareStatusResponse['status'],
  overrides: Partial<PlanPrepareStatusResponse> = {},
): PlanPrepareStatusResponse {
  return {
    ok: status !== 'no_plan' && status !== 'operator_seat_mismatch',
    source: 'prepare_status',
    plan_id: 'plan_123_abc',
    operator_seat: 'op_1',
    correlation_id: 'plan_123_abc',
    status,
    plan_state: status === 'draft' ? 'draft'
      : status === 'planning' ? 'planning'
      : status === 'no_plan' ? null
      : 'mso_review',
    ack_status: ['acked_prepare_not_requested', 'prepared_awaiting_confirmation', 'prepare_rejected', 'requires_review'].includes(status as string) ? 'acknowledged' : null,
    prepare_request_id: ['prepared_awaiting_confirmation', 'prepare_rejected', 'requires_review'].includes(status as string) ? 'prep_req_1' : null,
    prepare_request_status: status === 'prepared_awaiting_confirmation' ? 'prepared'
      : status === 'prepare_rejected' ? 'rejected'
      : status === 'requires_review' ? 'requires_review'
      : null,
    prepared_action_id: status === 'prepared_awaiting_confirmation' ? 'cpa-1' : null,
    confirm_queue_status: status === 'prepared_awaiting_confirmation' ? 'pending_review' : null,
    authority_stage: status === 'prepared_awaiting_confirmation' ? 'confirm_pending' : 'intent',
    missing_requirements: [],
    error: null,
    execution_allowed: false,
    used_execution: false,
    runner_reachable_from_ui: false,
    ...overrides,
  }
}

const UNAVAILABLE: PlanPrepareStatusResponse = {
  ok: false,
  source: 'prepare_status',
  plan_id: 'plan_123_abc',
  operator_seat: 'op_1',
  correlation_id: null,
  status: 'unknown',
  plan_state: null,
  ack_status: null,
  prepare_request_id: null,
  prepare_request_status: null,
  prepared_action_id: null,
  confirm_queue_status: null,
  authority_stage: 'unknown',
  missing_requirements: [],
  error: 'unavailable',
  execution_allowed: false,
  used_execution: false,
  runner_reachable_from_ui: false,
}

beforeEach(() => {
  vi.clearAllMocks()
  // jsdom does not implement window.confirm — always return true for tests
  vi.stubGlobal('confirm', () => true)
})

// ── Label rendering ───────────────────────────────────────────────────────────

describe('PlanStatusIndicator — label rendering', () => {
  it('renders "Plan not found" for no_plan', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('no_plan', { ok: false, plan_state: null }))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/plan not found/i)).toBeInTheDocument())
  })

  it('renders "Draft" for draft status', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('draft'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/draft/i)).toBeInTheDocument())
  })

  it('renders "Planning" for planning status', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('planning'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/planning/i)).toBeInTheDocument())
  })

  it('renders "ACK Pending" for mso_review_ack_pending', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('mso_review_ack_pending'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/ack pending/i)).toBeInTheDocument())
  })

  it('renders "ACK Rejected" for mso_review_ack_rejected', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('mso_review_ack_rejected', { ack_status: 'rejected_for_review' }))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/ack rejected/i)).toBeInTheDocument())
  })

  it('renders "ACKed — Prepare Available" for acked_prepare_not_requested', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('acked_prepare_not_requested'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/acked.*prepare available/i)).toBeInTheDocument())
  })

  it('renders "Prepared — Awaiting Confirmation" for prepared_awaiting_confirmation', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/prepared.*awaiting confirmation/i)).toBeInTheDocument())
  })

  it('renders "Prepare Rejected" for prepare_rejected', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepare_rejected'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/prepare rejected/i)).toBeInTheDocument())
  })

  it('renders "Requires Review" for requires_review', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('requires_review'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/requires review/i)).toBeInTheDocument())
  })

  it('renders "Seat mismatch" for operator_seat_mismatch', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('operator_seat_mismatch', { ok: false }))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/seat mismatch/i)).toBeInTheDocument())
  })

  it('renders "Prepare status unavailable" when backend fails', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(UNAVAILABLE)
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/unavailable|unknown/i)).toBeInTheDocument())
  })
})

// ── Forbidden labels ──────────────────────────────────────────────────────────

describe('PlanStatusIndicator — forbidden labels', () => {
  const FORBIDDEN = ['execute', 'running', 'live', 'authorized', 'approved', 'completed']

  FORBIDDEN.forEach(label => {
    it(`never renders "${label}" for prepared_awaiting_confirmation`, async () => {
      vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
      const { container } = render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
      await waitFor(() => screen.getByText(/prepared.*awaiting confirmation/i))
      expect(container.textContent?.toLowerCase()).not.toContain(label)
    })
  })

  it('does not render "Execute" button', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/prepared.*awaiting confirmation/i))
    expect(screen.queryByRole('button', { name: /execute/i })).not.toBeInTheDocument()
  })
})

// ── Button visibility ─────────────────────────────────────────────────────────

describe('PlanStatusIndicator — button visibility', () => {
  it('shows Acknowledge button only for mso_review_ack_pending', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('mso_review_ack_pending'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/ack pending/i))
    expect(screen.getByRole('button', { name: /acknowledge/i })).toBeInTheDocument()
  })

  it('does not show Acknowledge button for other states', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('acked_prepare_not_requested'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/acked.*prepare available/i))
    expect(screen.queryByRole('button', { name: /acknowledge/i })).not.toBeInTheDocument()
  })

  it('shows Prepare for Review button only for acked_prepare_not_requested', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('acked_prepare_not_requested'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/acked.*prepare available/i))
    expect(screen.getByRole('button', { name: /prepare for review/i })).toBeInTheDocument()
  })

  it('does not show Prepare for Review button for prepared state', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/prepared.*awaiting confirmation/i))
    expect(screen.queryByRole('button', { name: /prepare for review/i })).not.toBeInTheDocument()
  })
})

// ── Action: ACK ───────────────────────────────────────────────────────────────

describe('PlanStatusIndicator — ACK action', () => {
  it('calls ackPlan with ack_status=acknowledged when Acknowledge clicked', async () => {
    vi.mocked(getPlanPrepareStatus)
      .mockResolvedValueOnce(makeStatus('mso_review_ack_pending'))
      .mockResolvedValueOnce(makeStatus('acked_prepare_not_requested'))
    vi.mocked(ackPlan).mockResolvedValue({
      ok: true,
      source: 'plan_mso_ack',
      plan_id: 'plan_123_abc',
      ack: { ack_id: 'ack_1', plan_id: 'plan_123_abc', operator_seat: 'op_1', ack_status: 'acknowledged', acknowledged_by: 'op_1', acknowledged_at: '', note: null, source: 'plan_mso_ack', execution_allowed: false, used_execution: false, runner_reachable_from_ui: false },
    })

    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByRole('button', { name: /acknowledge/i }))
    fireEvent.click(screen.getByRole('button', { name: /acknowledge/i }))

    await waitFor(() => expect(ackPlan).toHaveBeenCalledWith(
      'plan_123_abc',
      expect.objectContaining({ ack_status: 'acknowledged', operator_seat: 'op_1' }),
    ))
  })
})

// ── Action: Prepare ───────────────────────────────────────────────────────────

describe('PlanStatusIndicator — Prepare action', () => {
  it('calls preparePlan with confirmation_acknowledged=true when Prepare clicked', async () => {
    vi.mocked(getPlanPrepareStatus)
      .mockResolvedValueOnce(makeStatus('acked_prepare_not_requested'))
      .mockResolvedValueOnce(makeStatus('prepared_awaiting_confirmation'))
    vi.mocked(preparePlan).mockResolvedValue({
      ok: true,
      source: 'prepare_contract',
      plan_id: 'plan_123_abc',
      prepare_request_id: 'prep_req_1',
      prepared_action_id: 'cpa-1',
      correlation_id: 'plan_123_abc',
      prepare_status: 'prepared',
      fail_closed_reason: null,
      execution_allowed: false,
      used_execution: false,
      runner_reachable_from_ui: false,
    })

    render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByRole('button', { name: /prepare for review/i }))
    fireEvent.click(screen.getByRole('button', { name: /prepare for review/i }))

    await waitFor(() => expect(preparePlan).toHaveBeenCalledWith(
      'plan_123_abc',
      expect.objectContaining({ confirmation_acknowledged: true, operator_seat: 'op_1' }),
    ))
  })
})

// ── Static: no forbidden button labels ────────────────────────────────────────

describe('PlanStatusIndicator — static label contract', () => {
  it('never renders "Ready to execute" in any state', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
    const { container } = render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/prepared.*awaiting confirmation/i))
    expect(container.textContent?.toLowerCase()).not.toContain('ready to execute')
  })

  it('never renders "Authorized" label in any state', async () => {
    vi.mocked(getPlanPrepareStatus).mockResolvedValue(makeStatus('prepared_awaiting_confirmation'))
    const { container } = render(<PlanStatusIndicator planId="plan_123_abc" operatorSeat="op_1" />)
    await waitFor(() => screen.getByText(/prepared.*awaiting confirmation/i))
    expect(container.textContent?.toLowerCase()).not.toMatch(/\bauthorized\b/)
  })
})
