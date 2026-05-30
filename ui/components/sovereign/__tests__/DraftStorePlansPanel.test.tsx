import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { PlanListResponse, PlanDraftRecord, PlanDraftResponse } from '@/lib/types'

// ── Mock all API helpers ──────────────────────────────────────────────────────
vi.mock('@/lib/api', () => ({
  listPlans:          vi.fn(),
  createPlan:         vi.fn(),
  transitionPlan:     vi.fn(),
  abandonPlan:        vi.fn(),
  getPlanPrepareStatus: vi.fn(),
  ackPlan:            vi.fn(),
  preparePlan:        vi.fn(),
}))

// ── Mock PlanStatusIndicator (avoid full prepare-status fetch in these tests) ─
vi.mock('../PlanStatusIndicator', () => ({
  PlanStatusIndicator: ({ planId }: { planId: string }) => (
    <div data-testid={`plan-status-${planId}`}>PlanStatusIndicator:{planId}</div>
  ),
}))

// ── Mock PlanStateBadge ────────────────────────────────────────────────────────
vi.mock('../PlanStateBadge', () => ({
  PlanStateBadge: ({ state }: { state: string }) => (
    <span data-testid="plan-state-badge">{state}</span>
  ),
}))

import { listPlans, createPlan, transitionPlan } from '@/lib/api'
import { DraftStorePlansPanel } from '../DraftStorePlansPanel'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const NOW = '2026-05-30T00:00:00.000Z'

function makePlan(overrides: Partial<PlanDraftRecord> = {}): PlanDraftRecord {
  return {
    plan_id: 'plan_1748476800000_a3f9c2e1',
    title: 'Test Plan',
    intent_summary: 'Test intent',
    domain: 'CODE',
    state: 'draft',
    operator_seat: 'op_1',
    schema_version: '1',
    created_at: NOW,
    updated_at: NOW,
    risk_level: 'low',
    target_actions: ['CODE_REVIEW'],
    ...overrides,
  }
}

function makeListResponse(plans: PlanDraftRecord[]): PlanListResponse {
  return {
    ok: true,
    source: 'draft_store',
    execution_allowed: false,
    used_execution: false,
    runner_reachable_from_ui: false,
    count: plans.length,
    plans,
  }
}

const EMPTY_LIST: PlanListResponse = makeListResponse([])

const UNAVAILABLE_LIST: PlanListResponse = {
  ok: false,
  source: 'draft_store',
  execution_allowed: false,
  used_execution: false,
  runner_reachable_from_ui: false,
  count: 0,
  plans: [],
  error: 'Draft store backend unavailable',
}

function makePlanResponse(plan: PlanDraftRecord): PlanDraftResponse {
  return {
    ok: true,
    source: 'draft_store',
    execution_allowed: false,
    used_execution: false,
    runner_reachable_from_ui: false,
    plan,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
  vi.stubGlobal('confirm', () => true)
  // Stub crypto.randomUUID for plan_id generation
  vi.stubGlobal('crypto', {
    randomUUID: () => 'a3f9c2e1-0000-0000-0000-000000000000',
  })
})

// ── Rendering ────────────────────────────────────────────────────────────────

describe('DraftStorePlansPanel — rendering', () => {
  it('renders operator seat input', () => {
    render(<DraftStorePlansPanel />)
    expect(screen.getByPlaceholderText(/operator_seat/i)).toBeInTheDocument()
  })

  it('does not call listPlans without operator seat', () => {
    render(<DraftStorePlansPanel />)
    expect(listPlans).not.toHaveBeenCalled()
  })

  it('calls listPlans when operator seat entered and refresh triggered', async () => {
    vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
    render(<DraftStorePlansPanel />)
    fireEvent.change(screen.getByPlaceholderText(/operator_seat/i), {
      target: { value: 'op_1' },
    })
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))
    await waitFor(() => expect(listPlans).toHaveBeenCalledWith('op_1'))
  })

  it('renders list of plans when loaded', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan()]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText('Test Plan')).toBeInTheDocument())
  })

  it('renders PlanStateBadge for each plan', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan()]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByTestId('plan-state-badge')).toBeInTheDocument())
  })

  it('renders PlanStatusIndicator for each plan', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan()]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() =>
      expect(screen.getByTestId('plan-status-plan_1748476800000_a3f9c2e1')).toBeInTheDocument()
    )
  })

  it('shows empty state when no plans', async () => {
    vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/no plans/i)).toBeInTheDocument())
  })

  it('shows error state when backend unavailable', async () => {
    vi.mocked(listPlans).mockResolvedValue(UNAVAILABLE_LIST)
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument())
  })
})

// ── Create Plan ───────────────────────────────────────────────────────────────

describe('DraftStorePlansPanel — create plan', () => {
  it('shows create plan toggle button', async () => {
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /\+ create plan/i })).toBeInTheDocument()
    )
  })

  // Helper to open the create form
  async function openCreateForm() {
    const toggleBtn = await screen.findByRole('button', { name: /\+ create plan/i })
    fireEvent.click(toggleBtn)
    // Now the form fields are visible
    await screen.findByPlaceholderText(/mission objective|title/i)
  }

  it('calls createPlan with required fields when submitted', async () => {
    vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
    vi.mocked(createPlan).mockResolvedValue(makePlanResponse(makePlan()))

    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await openCreateForm()

    fireEvent.change(screen.getByPlaceholderText(/mission objective|title/i), {
      target: { value: 'New Plan Title' },
    })
    fireEvent.change(screen.getByPlaceholderText(/intent|summary/i), {
      target: { value: 'Plan intent' },
    })
    fireEvent.change(screen.getByPlaceholderText(/domain/i), {
      target: { value: 'CODE' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^create plan$/i }))

    await waitFor(() =>
      expect(createPlan).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New Plan Title',
          intent_summary: 'Plan intent',
          domain: 'CODE',
          operator_seat: 'op_1',
          state: 'draft',
        }),
      )
    )
  })

  it('createPlan payload never contains forbidden fields', async () => {
    vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
    vi.mocked(createPlan).mockResolvedValue(makePlanResponse(makePlan()))

    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await openCreateForm()

    fireEvent.change(screen.getByPlaceholderText(/mission objective|title/i), {
      target: { value: 'T' },
    })
    fireEvent.change(screen.getByPlaceholderText(/intent|summary/i), {
      target: { value: 'I' },
    })
    fireEvent.change(screen.getByPlaceholderText(/domain/i), {
      target: { value: 'CODE' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^create plan$/i }))

    await waitFor(() => expect(createPlan).toHaveBeenCalled())
    const [payload] = vi.mocked(createPlan).mock.calls[0]
    const forbidden = [
      'execution_allowed', 'execution_status', 'executionState',
      'used_execution', 'policy_decision_ref', 'governance_ref',
      'capability_token_ref', 'authority_artifact_ref', 'runner_ref',
      'mission_id', 'prepared_action_id',
    ]
    for (const key of forbidden) {
      expect(payload).not.toHaveProperty(key)
    }
  })

  it('create plan payload has plan_id in correct format', async () => {
    vi.mocked(listPlans).mockResolvedValue(EMPTY_LIST)
    vi.mocked(createPlan).mockResolvedValue(makePlanResponse(makePlan()))

    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await openCreateForm()

    fireEvent.change(screen.getByPlaceholderText(/mission objective|title/i), { target: { value: 'T' } })
    fireEvent.change(screen.getByPlaceholderText(/intent|summary/i), { target: { value: 'I' } })
    fireEvent.change(screen.getByPlaceholderText(/domain/i), { target: { value: 'CODE' } })
    fireEvent.click(screen.getByRole('button', { name: /^create plan$/i }))

    await waitFor(() => expect(createPlan).toHaveBeenCalled())
    const [payload] = vi.mocked(createPlan).mock.calls[0]
    expect(payload.plan_id).toMatch(/^plan_\d+_[a-f0-9]+$/)
  })
})

// ── Escalate to MSO Review ────────────────────────────────────────────────────

describe('DraftStorePlansPanel — escalate to MSO review', () => {
  it('shows Escalate button for draft plans', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan({ state: 'draft' })]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /escalate/i })).toBeInTheDocument()
    )
  })

  it('shows Escalate button for planning plans', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan({ state: 'planning' })]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /escalate/i })).toBeInTheDocument()
    )
  })

  it('does not show Escalate button for mso_review plans', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan({ state: 'mso_review' })]))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => screen.getByText('Test Plan'))
    expect(screen.queryByRole('button', { name: /escalate/i })).not.toBeInTheDocument()
  })

  it('requires explicit confirmation before escalating', async () => {
    vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan({ state: 'draft' })]))
    vi.mocked(transitionPlan).mockResolvedValue(makePlanResponse(makePlan({ state: 'mso_review' })))
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => screen.getByRole('button', { name: /escalate/i }))
    fireEvent.click(screen.getByRole('button', { name: /escalate/i }))

    expect(confirmSpy).toHaveBeenCalled()
    expect(transitionPlan).not.toHaveBeenCalled()
  })

  it('calls transitionPlan with to_state=mso_review when confirmed', async () => {
    vi.mocked(listPlans)
      .mockResolvedValueOnce(makeListResponse([makePlan({ state: 'draft' })]))
      .mockResolvedValue(makeListResponse([makePlan({ state: 'mso_review' })]))
    vi.mocked(transitionPlan).mockResolvedValue(makePlanResponse(makePlan({ state: 'mso_review' })))

    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => screen.getByRole('button', { name: /escalate/i }))
    fireEvent.click(screen.getByRole('button', { name: /escalate/i }))

    await waitFor(() =>
      expect(transitionPlan).toHaveBeenCalledWith(
        'plan_1748476800000_a3f9c2e1',
        expect.objectContaining({
          operator_seat: 'op_1',
          to_state: 'mso_review',
        }),
      )
    )
  })
})

// ── Forbidden labels ──────────────────────────────────────────────────────────

const FORBIDDEN_LABELS = ['execute', 'running', 'live', 'authorized', 'approved', 'completed']

describe('DraftStorePlansPanel — forbidden labels', () => {
  FORBIDDEN_LABELS.forEach(label => {
    it(`never renders "${label}" button`, async () => {
      vi.mocked(listPlans).mockResolvedValue(makeListResponse([makePlan()]))
      render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
      await waitFor(() => screen.getByText('Test Plan'))
      expect(screen.queryByRole('button', { name: new RegExp(label, 'i') })).not.toBeInTheDocument()
    })
  })

  it('never renders "Execute" button in any state', async () => {
    const plans = [
      makePlan({ state: 'draft' }),
      makePlan({ plan_id: 'plan_2', state: 'planning' }),
      makePlan({ plan_id: 'plan_3', state: 'mso_review' }),
    ]
    vi.mocked(listPlans).mockResolvedValue(makeListResponse(plans))
    render(<DraftStorePlansPanel defaultOperatorSeat="op_1" />)
    await waitFor(() => screen.getAllByText('Test Plan'))
    expect(screen.queryByRole('button', { name: /^execute$/i })).not.toBeInTheDocument()
  })
})
