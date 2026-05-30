import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// ── Mock polling hooks (no-ops in test environment) ───────────────────────────
vi.mock('@/hooks/use-seat-provider-polling',   () => ({ useSeatProviderPolling:   vi.fn() }))
vi.mock('@/hooks/use-prepared-actions-polling', () => ({ usePreparedActionsPolling: vi.fn() }))
vi.mock('@/hooks/use-confirm-pending-polling',  () => ({ useConfirmPendingPolling:  vi.fn() }))
vi.mock('@/hooks/use-authority-status-polling', () => ({ useAuthorityStatusPolling: vi.fn() }))
vi.mock('@/hooks/use-outcome-status-polling',   () => ({ useOutcomeStatusPolling:   vi.fn() }))

// ── Mock entity registry ──────────────────────────────────────────────────────
vi.mock('@/lib/sovereign/entity-registry', () => ({
  getEntity: vi.fn(() => ({ id: 'mission_control', execution_policy: 'read_only' })),
}))

// ── Mock truth-contract API helpers ───────────────────────────────────────────
// These are the four new backend truth-contract endpoints (Tasks 2–5).
// Default to unavailable so all tests start with honest empty state.
vi.mock('@/lib/api', () => ({
  getMissionControlStatus:             vi.fn(),
  getMissionControlReadiness:          vi.fn(),
  getOrchestrationSnapshot:            vi.fn(),
  getAuthorityTraceSnapshot:           vi.fn(),
  getMissionControlLifecycleSnapshot:  vi.fn(),
  // Draft Store plan helpers (Sprint #228/#233)
  listPlans:           vi.fn().mockResolvedValue({ ok: false, source: 'draft_store', execution_allowed: false, used_execution: false, runner_reachable_from_ui: false, count: 0, plans: [], error: 'unavailable' }),
  createPlan:          vi.fn(),
  updatePlan:          vi.fn(),
  transitionPlan:      vi.fn(),
  abandonPlan:         vi.fn(),
  // Prepare contract helpers (Sprint #230/#231/#232)
  getPlanPrepareStatus: vi.fn().mockResolvedValue({ ok: false, source: 'prepare_status', plan_id: '', operator_seat: '', correlation_id: null, status: 'unknown', plan_state: null, ack_status: null, prepare_request_id: null, prepare_request_status: null, prepared_action_id: null, confirm_queue_status: null, authority_stage: 'unknown', missing_requirements: [], error: 'unavailable', execution_allowed: false, used_execution: false, runner_reachable_from_ui: false }),
  ackPlan:             vi.fn(),
  preparePlan:         vi.fn(),
}))

// ── Unavailable fixture constants ─────────────────────────────────────────────

const MC_STATUS_UNAVAILABLE = {
  ok: false,
  source: 'backend_read_model' as const,
  execution_allowed: false as const,
  used_execution: false as const,
  runner_reachable_from_ui: false as const,
  mission_control: { state: 'unavailable' as const, mode: 'read_model' as const, execution_allowed: false as const, used_execution: false as const },
  mso: { entity_status: 'unavailable' as const, seat_status: 'unavailable' as const, boundary: 'sovereign' },
  queues: { prepared_actions_count: 0, confirm_pending_count: 0 },
  authority: { status: 'unavailable' as const, counts: {} },
  outcome: { status: 'unavailable' as const, found: false, execution_closed: true as const, sources_checked: [] as string[] },
  error: 'unavailable',
}

const MC_READINESS_UNAVAILABLE = {
  ok: false,
  source: 'backend_read_model' as const,
  execution_allowed: false as const,
  used_execution: false as const,
  runner_reachable_from_ui: false as const,
  arms: [],
  system: { overall: 'unavailable' as const },
  error: 'unavailable',
}

const ORCHESTRATION_SNAPSHOT_UNAVAILABLE = {
  ok: false,
  source: 'backend_read_model' as const,
  execution_allowed: false as const,
  used_execution: false as const,
  runner_reachable_from_ui: false as const,
  runs: [] as never[],
  threads: [] as never[],
  prepared_actions: [],
  confirm_pending: [],
  live_execution: false as const,
  event_stream_connected: false as const,
  error: 'unavailable',
}

const AUTHORITY_TRACE_UNAVAILABLE = {
  ok: false,
  source: 'backend_read_model' as const,
  execution_allowed: false as const,
  used_execution: false as const,
  runner_reachable_from_ui: false as const,
  trace_mode: 'unavailable' as const,
  stages: [],
  error: 'unavailable',
}

const LC_SNAPSHOT_UNAVAILABLE = {
  ok: false,
  source: 'backend_read_model' as const,
  execution_allowed: false as const,
  used_execution: false as const,
  runner_reachable_from_ui: false as const,
  current_stage: 'planning' as const,
  queues_at_snapshot: { prepared_actions_count: 0, confirm_pending_count: 0 },
  error: 'unavailable',
}

// ── Import component and mocked helpers after vi.mock declarations ────────────
// Imports are hoisted by Vitest, so these get the mocked versions.
import { MissionControlView } from '../MissionControlView'
import {
  getMissionControlStatus,
  getMissionControlReadiness,
  getOrchestrationSnapshot,
  getAuthorityTraceSnapshot,
  getMissionControlLifecycleSnapshot,
} from '@/lib/api'
import { useConfirmPendingStore } from '@/stores/confirm-pending-store'
import { useSovereignStore } from '@/stores/sovereign-store'

// ── Mock fetch (fail-soft: direct fetch calls in MSOEscalationSpace) ──────────
beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({ ok: false, source: 'test', execution_allowed: false, used_execution: false, cognitive_only: true }),
      { status: 200 },
    ),
  )

  // Default all truth-contract helpers to unavailable (imported above, mocked by vi.mock)
  vi.mocked(getMissionControlStatus).mockResolvedValue(MC_STATUS_UNAVAILABLE)
  vi.mocked(getMissionControlReadiness).mockResolvedValue(MC_READINESS_UNAVAILABLE)
  vi.mocked(getOrchestrationSnapshot).mockResolvedValue(ORCHESTRATION_SNAPSHOT_UNAVAILABLE)
  vi.mocked(getAuthorityTraceSnapshot).mockResolvedValue(AUTHORITY_TRACE_UNAVAILABLE)
  vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue(LC_SNAPSHOT_UNAVAILABLE)
})

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Click the tab button matching a label. There may be multiple text nodes for
 *  the same label (tab bar + lifecycle strip), so we pick the first button ancestor. */
function clickTab(label: string) {
  const nodes = screen.getAllByText(label)
  const btn   = nodes.map(n => n.closest('button')).find(Boolean)
  if (btn) fireEvent.click(btn)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MissionControlView — Mission Control Cockpit', () => {
  it('renders the Mission Control header', () => {
    render(<MissionControlView />)
    expect(screen.getByText(/Mission Control/i)).toBeInTheDocument()
  })

  it('renders the lifecycle progression hint', () => {
    render(<MissionControlView />)
    expect(screen.getAllByText('Planner').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MSO').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Arms').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Orchestration').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Outcome').length).toBeGreaterThan(0)
  })

  it('shows all 5 tabs in the tab bar', () => {
    render(<MissionControlView />)
    for (const label of ['Planner', 'MSO', 'Arms', 'Orchestration', 'Outcome']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('opens the Planner space by default', () => {
    render(<MissionControlView />)
    // Sprint #233: PlannerSpace now shows Draft Store Plans Panel as primary surface
    expect(screen.getByText(/Draft Store — Sovereign Plan Persistence/i)).toBeInTheDocument()
  })
})

describe('PlannerSpace — Space 1', () => {
  it('renders operator seat input for Draft Store Panel', () => {
    render(<MissionControlView />)
    expect(screen.getByPlaceholderText(/operator_seat/i)).toBeInTheDocument()
  })

  it('renders Refresh Plans button', () => {
    render(<MissionControlView />)
    expect(screen.getByRole('button', { name: /refresh plans/i })).toBeInTheDocument()
  })

  it('renders Create Plan toggle button', () => {
    render(<MissionControlView />)
    expect(screen.getByRole('button', { name: /\+ create plan/i })).toBeInTheDocument()
  })

  it('shows MSO Chat Composer Helper (collapsed)', () => {
    render(<MissionControlView />)
    expect(screen.getByText(/MSO Chat Composer Helper/i)).toBeInTheDocument()
  })

  it('shows Manual Plan Status Lookup (collapsed)', () => {
    render(<MissionControlView />)
    expect(screen.getByText(/Manual Plan Status Lookup/i)).toBeInTheDocument()
  })

  it('plan starts in draft state (LifecycleBadge) inside chat helper', () => {
    render(<MissionControlView />)
    // Expand the chat helper section
    fireEvent.click(screen.getByText(/MSO Chat Composer Helper/i))
    const allDraft = screen.getAllByText(/\bdraft\b/i)
    expect(allDraft.length).toBeGreaterThan(0)
  })

  it('does NOT suggest direct execution from planner', () => {
    render(<MissionControlView />)
    expect(screen.queryByText(/execute now/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/run plan/i)).not.toBeInTheDocument()
  })

  it('states that escalation does not trigger execution', () => {
    render(<MissionControlView />)
    const matches = screen.getAllByText(/no execution is triggered/i)
    expect(matches.length).toBeGreaterThan(0)
  })
})

describe('MSOEscalationSpace — Space 2', () => {
  it('renders the MSO escalation header', () => {
    render(<MissionControlView />)
    clickTab('MSO')
    expect(screen.getByText(/MSO Escalation.*Governed Preparation/i)).toBeInTheDocument()
  })

  it('states that execution remains closed', () => {
    render(<MissionControlView />)
    clickTab('MSO')
    expect(screen.getByText(/execution remains closed/i)).toBeInTheDocument()
  })

  it('shows Execution Now Allowed = No (governed preparation invariant)', () => {
    render(<MissionControlView />)
    clickTab('MSO')
    expect(screen.getByText('Execution Now Allowed')).toBeInTheDocument()
  })

  it('shows execution_allowed=false note after entity status loads', async () => {
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.getByText(/execution_allowed=false/i)).toBeInTheDocument()
    })
  })

  it('shows used_execution=false note after seat status loads', async () => {
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.getByText(/used_execution=false/i)).toBeInTheDocument()
    })
  })

  it('shows full authority chain requirement', () => {
    render(<MissionControlView />)
    clickTab('MSO')
    expect(screen.getByText(/PolicyDecision.*CapabilityToken.*PoliceGate/i)).toBeInTheDocument()
  })

  it('nextStage is never "running" — shows "blocked" when confirm queue has items', () => {
    // Set confirm pending count > 0 so currentStage becomes awaiting_confirmation
    useConfirmPendingStore.setState({
      confirmPending: {
        ok: true,
        source: 'confirm_flow',
        note: 'test',
        pending_count: 1,
        expired_pending_count: 0,
        pending: [],
      },
      isPolling: false,
      lastPolled: null,
      pollError: null,
    })
    render(<MissionControlView />)
    clickTab('MSO')
    // 'running' must not appear as a lifecycle badge or label
    expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
    // 'blocked' should appear as the next required stage
    expect(screen.getByText(/^blocked$/i)).toBeInTheDocument()
    // Cleanup store state
    useConfirmPendingStore.setState({ confirmPending: null })
  })
})

describe('ArmsAvailabilitySpace — Space 3', () => {
  it('renders the Arms availability header', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    expect(screen.getByText(/Arms.*Executor Availability.*ALPHA/i)).toBeInTheDocument()
  })

  it('states it is not a direct execution launcher', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    expect(screen.getByText(/not a direct execution launcher/i)).toBeInTheDocument()
  })

  it('states execution is architecturally prohibited from this panel', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    expect(screen.getByText(/architecturally prohibited/i)).toBeInTheDocument()
  })

  it('shows registry source label', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    const matches = screen.queryAllByText(/Registry source/i)
    expect(matches.length).toBeGreaterThan(0)
  })

  it('reports executionStatus as unavailable when no arms registered', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    expect(screen.getByText(/executionStatus: unavailable/i)).toBeInTheDocument()
  })

  it('shows backend_read_model source when readiness returns ok', async () => {
    vi.mocked(getMissionControlReadiness).mockResolvedValue({
      ...MC_READINESS_UNAVAILABLE,
      ok: true,
      arms: [
        {
          id: 'test-arm',
          label: 'Test Arm',
          available: true,
          execution_status: 'unavailable',
          readiness_source: 'agent_registry',
          can_execute_without_mso: false,
          requires_authority: true,
        },
      ],
      system: { overall: 'available' },
    })
    render(<MissionControlView />)
    clickTab('Arms')
    await waitFor(() => {
      expect(screen.getByText('backend_read_model')).toBeInTheDocument()
    })
  })

  it('renders backend arm name and source when readiness ok', async () => {
    vi.mocked(getMissionControlReadiness).mockResolvedValue({
      ...MC_READINESS_UNAVAILABLE,
      ok: true,
      arms: [
        {
          id: 'my-arm',
          label: 'My Agent Arm',
          available: true,
          execution_status: 'unavailable',
          readiness_source: 'agent_registry',
          can_execute_without_mso: false,
          requires_authority: true,
        },
      ],
      system: { overall: 'available' },
    })
    render(<MissionControlView />)
    clickTab('Arms')
    await waitFor(() => {
      expect(screen.getByText('My Agent Arm')).toBeInTheDocument()
      expect(screen.getByText(/source: agent_registry/i)).toBeInTheDocument()
    })
  })

  it('backend arm availability does NOT imply authorization (invariants visible)', async () => {
    vi.mocked(getMissionControlReadiness).mockResolvedValue({
      ...MC_READINESS_UNAVAILABLE,
      ok: true,
      arms: [
        {
          id: 'auth-arm',
          label: 'Authorized Arm',
          available: true,
          execution_status: 'unavailable',
          readiness_source: 'agent_registry',
          can_execute_without_mso: false,
          requires_authority: true,
        },
      ],
      system: { overall: 'available' },
    })
    render(<MissionControlView />)
    clickTab('Arms')
    await waitFor(() => {
      // Authorization invariants must always be visible — arm availability ≠ authorization
      expect(screen.getByText(/can_execute_without_mso: false/i)).toBeInTheDocument()
      expect(screen.getByText(/requires_authority: true/i)).toBeInTheDocument()
    })
  })

  it('falls back to derived data when readiness returns ok:false', async () => {
    // Default mock is already ok:false — just verify fallback label appears
    render(<MissionControlView />)
    clickTab('Arms')
    // When backend is unavailable, derived fallback label appears
    await waitFor(() => {
      expect(screen.getByText(/\[derived fallback\]/i)).toBeInTheDocument()
    })
  })

  it('backend ok:false does not become fake operational success in Arms', async () => {
    // Default mock returns ok:false — no arms should appear from backend
    render(<MissionControlView />)
    clickTab('Arms')
    // Should NOT show backend_read_model as source (that only appears when ok=true)
    await waitFor(() => {
      expect(screen.queryByText(/^backend_read_model$/)).not.toBeInTheDocument()
    })
  })
})

describe('OrchestrationViewSpace — Space 4', () => {
  it('renders the Orchestration view header', () => {
    render(<MissionControlView />)
    clickTab('Orchestration')
    expect(screen.getByText(/Orchestration View — ALPHA/i)).toBeInTheDocument()
  })

  it('does NOT fabricate running threads when queue is empty', () => {
    render(<MissionControlView />)
    clickTab('Orchestration')
    expect(screen.getByText(/No active orchestration threads/i)).toBeInTheDocument()
  })

  it('states execution remains closed in the orchestration header', () => {
    render(<MissionControlView />)
    clickTab('Orchestration')
    const matches = screen.queryAllByText(/execution remains closed/i)
    expect(matches.length).toBeGreaterThan(0)
  })

  it('states executionStatus is unavailable in ALPHA', () => {
    render(<MissionControlView />)
    clickTab('Orchestration')
    expect(screen.getByText(/execution is closed until full authority chain/i)).toBeInTheDocument()
  })

  it('does NOT fabricate live activity', () => {
    render(<MissionControlView />)
    clickTab('Orchestration')
    expect(screen.queryByText(/thread is running/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/active execution/i)).not.toBeInTheDocument()
  })

  it('backend snapshot shows live_execution: false invariant', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      prepared_actions: [],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      expect(screen.getByText(/live_execution: false/i)).toBeInTheDocument()
    })
  })

  it('backend snapshot empty runs and threads never shows running state', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      // runs: [], threads: [] always — this is the truth contract
      prepared_actions: [],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      // No running badge should appear
      expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
      // The empty-state message should appear
      expect(screen.getByText(/No active orchestration threads/i)).toBeInTheDocument()
    })
  })

  it('backend prepared_actions render with status=prepared (not running)', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      prepared_actions: [
        { id: 'pa-001', status: 'prepared', domain: 'WORK', intent: 'Schedule standup meeting' },
      ],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      expect(screen.getByText('Schedule standup meeting')).toBeInTheDocument()
      // Status shown is 'prepared' — never 'running'
      expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
    })
  })

  it('backend ok:false orchestration does not fabricate success', async () => {
    // Default mock is ok:false — Zustand stores are empty too
    render(<MissionControlView />)
    clickTab('Orchestration')
    // No fabricated "available" or "running" — just the empty state
    expect(screen.queryByText(/execution succeeded/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/thread is running/i)).not.toBeInTheDocument()
  })

  it('shows runner_reachable_from_ui: false invariant', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      prepared_actions: [],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      expect(screen.getByText(/runner_reachable_from_ui: false/i)).toBeInTheDocument()
    })
  })

  it('renders confirm-pending-item cards when orchestration snapshot has items', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      prepared_actions: [],
      confirm_pending: [
        {
          id: 'qe-test-alpha-001',
          status: 'awaiting_confirmation',
          domain: 'COGNITIVE',
          intent: 'Review the Q2 proposal draft',
          requested_action: 'review_document',
          execution_allowed: false,
          can_execute_now: false,
        },
      ],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      expect(screen.getByTestId('confirm-pending-item')).toBeInTheDocument()
      expect(screen.getByText(/COGNITIVE/i)).toBeInTheDocument()
      expect(screen.getByText(/Review the Q2 proposal draft/i)).toBeInTheDocument()
    })
  })

  it('confirm-pending-item cards always show execution_allowed: false and can_execute_now: false', async () => {
    vi.mocked(getOrchestrationSnapshot).mockResolvedValue({
      ...ORCHESTRATION_SNAPSHOT_UNAVAILABLE,
      ok: true,
      prepared_actions: [],
      confirm_pending: [
        {
          id: 'qe-test-alpha-002',
          status: 'awaiting_confirmation',
          domain: 'WORK',
          intent: 'Schedule team meeting',
          requested_action: 'create_calendar_event',
          execution_allowed: false,
          can_execute_now: false,
        },
      ],
    })
    render(<MissionControlView />)
    clickTab('Orchestration')
    await waitFor(() => {
      expect(screen.getByText(/execution_allowed: false/i)).toBeInTheDocument()
      expect(screen.getByText(/can_execute_now: false/i)).toBeInTheDocument()
    })
  })
})

describe('OutcomeTraceSpace — Space 5', () => {
  it('renders the Outcome + Authority Trace header', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    expect(screen.getByText(/Outcome.*Authority Trace.*ALPHA/i)).toBeInTheDocument()
  })

  it('renders all 9 authority chain stage labels (hardcoded fallback)', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    for (const label of [
      'MSO Kernel', 'Intent Contract', 'Policy', 'Governance', 'CapabilityToken',
      'Police Gate', 'AuthorityArtifact', 'Runner',
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    expect(screen.getAllByText('Outcome').length).toBeGreaterThan(0)
  })

  it('marks Runner and Outcome stages as closed', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    const closedBadges = screen.getAllByText('closed')
    expect(closedBadges.length).toBeGreaterThanOrEqual(2)
  })

  it('states the authority trace is read-only', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    expect(screen.getByText(/are architecturally closed to UI/i)).toBeInTheDocument()
  })

  it('renders the Outcome Status panel header', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    const matches = screen.getAllByText(/Outcome Status/i)
    expect(matches.length).toBeGreaterThan(0)
  })

  it('does NOT fabricate outcome success data', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    expect(screen.queryByText(/execution succeeded/i)).not.toBeInTheDocument()
  })

  it('shows trace_mode annotation (unavailable when backend fails)', async () => {
    // Default mock is ok:false — trace_mode should show 'unavailable'
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const label = screen.getByTestId('trace-mode-label')
      expect(label.textContent).toMatch(/unavailable.*derived fallback/i)
    })
  })

  it('shows trace_mode: snapshot when backend returns ok snapshot', async () => {
    vi.mocked(getAuthorityTraceSnapshot).mockResolvedValue({
      ...AUTHORITY_TRACE_UNAVAILABLE,
      ok: true,
      trace_mode: 'snapshot',
      stages: [
        { id: 'mso', label: 'MSO Kernel', state: 'available', evidence_ref: null },
        { id: 'runner', label: 'Runner', state: 'architectural', evidence_ref: null },
      ],
    })
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const label = screen.getByTestId('trace-mode-label')
      expect(label.textContent).toMatch(/snapshot.*backend_read_model/i)
    })
  })

  it('renders backend stages when trace snapshot is available', async () => {
    vi.mocked(getAuthorityTraceSnapshot).mockResolvedValue({
      ...AUTHORITY_TRACE_UNAVAILABLE,
      ok: true,
      trace_mode: 'snapshot',
      stages: [
        { id: 'mso', label: 'MSO Kernel', state: 'available', evidence_ref: null },
        { id: 'runner', label: 'Runner', state: 'architectural', evidence_ref: null },
      ],
    })
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      expect(screen.getAllByText('MSO Kernel').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Runner').length).toBeGreaterThan(0)
    })
  })

  it('architectural trace stage is NOT displayed as live runtime trace', async () => {
    vi.mocked(getAuthorityTraceSnapshot).mockResolvedValue({
      ...AUTHORITY_TRACE_UNAVAILABLE,
      ok: true,
      trace_mode: 'snapshot',
      stages: [
        { id: 'runner', label: 'Runner', state: 'architectural', evidence_ref: null },
      ],
    })
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const label = screen.getByTestId('trace-mode-label')
      // trace_mode is 'snapshot' — not 'live' — this is the key safety check
      expect(label.textContent).not.toMatch(/live/i)
      expect(label.textContent).toMatch(/snapshot/i)
    })
  })

  it('renders outcome-status-label testid in Outcome tab', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      outcome: { status: 'not_found', found: false, execution_closed: true, sources_checked: [] },
    })
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const label = screen.getByTestId('outcome-status-label')
      expect(label).toBeInTheDocument()
      expect(label.textContent).toBe('not_found')
    })
  })

  it('renders outcome-execution-closed testid always true', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      outcome: { status: 'unavailable', found: false, execution_closed: true, sources_checked: [] },
    })
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const el = screen.getByTestId('outcome-execution-closed')
      expect(el).toBeInTheDocument()
      expect(el.textContent).toBe('true')
    })
  })

  it('outcome-status-label shows unavailable when backend returns unavailable status', async () => {
    // Default mock — MC_STATUS_UNAVAILABLE has outcome.status = 'unavailable'
    render(<MissionControlView />)
    clickTab('Outcome')
    await waitFor(() => {
      const label = screen.getByTestId('outcome-status-label')
      expect(label.textContent).toBe('unavailable')
    })
  })

  it('backend ok:false falls back to hardcoded derived stages', async () => {
    // Default mock is ok:false — hardcoded stages should render
    render(<MissionControlView />)
    clickTab('Outcome')
    // Hardcoded fallback stages always include these labels
    expect(screen.getAllByText('Policy').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Police Gate').length).toBeGreaterThan(0)
  })
})

describe('Header — Backend MC State Badge', () => {
  it('shows mc:available badge when backend status returns available', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      mission_control: { state: 'available', mode: 'read_model', execution_allowed: false, used_execution: false },
    })
    render(<MissionControlView />)
    await waitFor(() => {
      expect(screen.getByTestId('mc-state-badge')).toBeInTheDocument()
      expect(screen.getByTestId('mc-state-badge').textContent).toMatch(/mc:available/i)
    })
  })

  it('shows mc:partial badge when backend reports partial state', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      mission_control: { state: 'partial', mode: 'read_model', execution_allowed: false, used_execution: false },
    })
    render(<MissionControlView />)
    await waitFor(() => {
      expect(screen.getByTestId('mc-state-badge').textContent).toMatch(/mc:partial/i)
    })
  })

  it('shows mc:unavailable badge when backend status returns ok:false', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      mission_control: { state: 'unavailable', mode: 'read_model', execution_allowed: false, used_execution: false },
    })
    render(<MissionControlView />)
    await waitFor(() => {
      expect(screen.getByTestId('mc-state-badge').textContent).toMatch(/mc:unavailable/i)
    })
  })

  it('hides mc badge while backend status is loading (null state)', () => {
    // Mock never resolves — simulates loading state
    vi.mocked(getMissionControlStatus).mockReturnValue(new Promise(() => {}))
    render(<MissionControlView />)
    // Badge should not appear until data arrives
    expect(screen.queryByTestId('mc-state-badge')).not.toBeInTheDocument()
  })

  it('header shows prepared badge using mcStatus.queues.prepared_actions_count when backend available', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      queues: { prepared_actions_count: 3, confirm_pending_count: 0 },
      mission_control: { state: 'available', mode: 'read_model', execution_allowed: false, used_execution: false },
    })
    render(<MissionControlView />)
    await waitFor(() => {
      expect(screen.getByText(/3 prepared/i)).toBeInTheDocument()
    })
  })

  it('header shows confirm badge using mcStatus.queues.confirm_pending_count when backend available', async () => {
    vi.mocked(getMissionControlStatus).mockResolvedValue({
      ...MC_STATUS_UNAVAILABLE,
      ok: true,
      queues: { prepared_actions_count: 0, confirm_pending_count: 2 },
      mission_control: { state: 'available', mode: 'read_model', execution_allowed: false, used_execution: false },
    })
    render(<MissionControlView />)
    await waitFor(() => {
      expect(screen.getByText(/2 pending/i)).toBeInTheDocument()
    })
  })
})

describe('Mission Control — Global Invariants', () => {
  it('does not claim MSO executes', () => {
    render(<MissionControlView />)
    expect(screen.queryByText(/MSO executes/i)).not.toBeInTheDocument()
  })

  it('does not expose a standalone Run/Execute/Start button at the top level', () => {
    render(<MissionControlView />)
    expect(screen.queryByRole('button', { name: /^run$|^execute$|^start execution$/i })).not.toBeInTheDocument()
  })

  it('describes the full lifecycle in the cockpit header', () => {
    render(<MissionControlView />)
    expect(screen.getByText(/Planning.*MSO.*Governed Preparation.*Confirmation.*Orchestration.*Outcome/i)).toBeInTheDocument()
  })
})

// S-MISSION-CONTROL-LIFECYCLE-SNAPSHOT-01
describe('MSOEscalationSpace — lifecycle backend wiring', () => {
  it('uses backend current_stage when lifecycle snapshot returns prepared', async () => {
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ok: true,
      source: 'backend_read_model',
      execution_allowed: false,
      used_execution: false,
      runner_reachable_from_ui: false,
      current_stage: 'prepared',
      queues_at_snapshot: { prepared_actions_count: 2, confirm_pending_count: 0 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.getByText(/prepared/i)).toBeInTheDocument()
    })
  })

  it('falls back gracefully when lifecycle snapshot is loading (never resolves)', () => {
    vi.mocked(getMissionControlLifecycleSnapshot).mockImplementation(
      () => new Promise(() => {}), // never resolves — simulates loading
    )
    render(<MissionControlView />)
    clickTab('MSO')
    // Component must render without crash — Zustand fallback active
    expect(screen.getByText(/MSO Escalation/i)).toBeInTheDocument()
  })

  it('does not show running as current stage', async () => {
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ok: true,
      source: 'backend_read_model',
      execution_allowed: false,
      used_execution: false,
      runner_reachable_from_ui: false,
      current_stage: 'planning',
      queues_at_snapshot: { prepared_actions_count: 0, confirm_pending_count: 0 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
    })
  })
})

// S-MISSION-CONTROL-LANGUAGE-HARDENING-01
// These tests prove that LifecycleBadge and ExecStatusBadge never render
// dangerous execution language regardless of what value is passed to them.
// They test the guard maps directly via the rendered component.
describe('Language hardening — S-MISSION-CONTROL-LANGUAGE-HARDENING-01', () => {
  it('LifecycleBadge: rogue backend state "running" renders "blocked" not "running"', async () => {
    // Simulate a rogue or future-schema lifecycle value containing 'running'.
    // The DANGEROUS_LIFECYCLE_DISPLAY_MAP must intercept this before render.
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'running' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 1, confirm_pending_count: 1 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      // 'running' must never appear as a rendered lifecycle badge label
      expect(screen.queryByText(/^running$/i)).not.toBeInTheDocument()
      // The guard maps 'running' → 'blocked'. Expect 'blocked' to appear.
      const blockedEls = screen.getAllByText(/^blocked$/i)
      expect(blockedEls.length).toBeGreaterThan(0)
    })
  })

  it('LifecycleBadge: rogue backend state "executing" renders "blocked" not "executing"', async () => {
    // 'executing' is a forbidden display term — defense-in-depth guard.
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'executing' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 1, confirm_pending_count: 1 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    await waitFor(() => {
      expect(screen.queryByText(/^executing$/i)).not.toBeInTheDocument()
      const blockedEls = screen.getAllByText(/^blocked$/i)
      expect(blockedEls.length).toBeGreaterThan(0)
    })
  })

  it('LifecycleBadge: rogue backend state "completed" renders "closed" not "completed"', async () => {
    // 'completed' implies execution completed — impossible from this surface.
    // The guard maps 'completed' → 'closed'.
    vi.mocked(getMissionControlLifecycleSnapshot).mockResolvedValue({
      ...LC_SNAPSHOT_UNAVAILABLE,
      ok: true,
      current_stage: 'completed' as unknown as 'planning',
      queues_at_snapshot: { prepared_actions_count: 0, confirm_pending_count: 0 },
    })
    render(<MissionControlView />)
    clickTab('MSO')
    // Wait for 'blocked' to appear — nextStage always becomes 'blocked' when
    // currentStage is an unrecognised/non-standard value. Before async data loads,
    // nextStage is 'mso_review' (rendered as "mso review"). 'blocked' appearing
    // proves the async lifecycle data was received by the component.
    await waitFor(() => {
      expect(screen.getAllByText(/^blocked$/i).length).toBeGreaterThan(0)
    })
    // Now that async data is confirmed received: 'completed' must NOT be rendered.
    // The guard must have remapped 'completed' → 'closed' before rendering.
    expect(screen.queryByText(/^completed$/i)).not.toBeInTheDocument()
  })

  it('ExecStatusBadge: active Zustand arm renders "registered" not "real"', async () => {
    // Backend readiness unavailable (default ok:false) → Zustand fallback for arms.
    // With an active registered agent, mapExecStatus('active') = 'real' previously rendered "real".
    // After hardening, 'real' must be displayed as 'registered'.
    useSovereignStore.setState((s) => ({
      ...s,
      systemState: {
        ...s.systemState,
        registeredAgents: [
          {
            id: 'test-active-arm',
            name: 'Active Test Arm',
            domain: 'WORK',
            description: 'Test arm for language hardening',
            status: 'active',
            capabilities: [],
            last_execution_at: null,
            last_result: null,
            policy_restricted: false,
            requires_authority: true,
            requires_review: false,
          },
        ],
        agentRegistrySource: { status: 'available', lastCheckedAt: null, lastSuccessfulAt: null, error: null },
        totalAgents: 1,
      },
    }))
    render(<MissionControlView />)
    clickTab('Arms')
    await waitFor(() => {
      // 'real' must not appear as a badge text (execution-adjacent language)
      expect(screen.queryByText(/^real$/i)).not.toBeInTheDocument()
      // 'registered' must appear instead (honest description of arm status)
      expect(screen.getByText(/^registered$/i)).toBeInTheDocument()
    })
    // Cleanup: reset registered agents
    useSovereignStore.setState((s) => ({
      ...s,
      systemState: { ...s.systemState, registeredAgents: [], totalAgents: 0 },
    }))
  })
})
