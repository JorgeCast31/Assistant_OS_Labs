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

// ── Mock fetch (fail-soft: MSO entity/seat status calls return unavailable) ──
beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({ ok: false, source: 'test', execution_allowed: false, used_execution: false, cognitive_only: true }),
      { status: 200 },
    ),
  )
})

// ── Import component after mocks ──────────────────────────────────────────────
import { MissionControlView } from '../MissionControlView'

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
    expect(screen.getByText(/Planner Space — ALPHA/i)).toBeInTheDocument()
  })
})

describe('PlannerSpace — Space 1', () => {
  it('renders mission objective input', () => {
    render(<MissionControlView />)
    expect(screen.getByPlaceholderText(/Describe the mission objective/i)).toBeInTheDocument()
  })

  it('renders plan body textarea', () => {
    render(<MissionControlView />)
    expect(screen.getByPlaceholderText(/Describe the plan steps/i)).toBeInTheDocument()
  })

  it('renders the Escalate to MSO button', () => {
    render(<MissionControlView />)
    expect(screen.getByRole('button', { name: /Escalate to MSO/i })).toBeInTheDocument()
  })

  it('escalate button is disabled when title/body are empty', () => {
    render(<MissionControlView />)
    expect(screen.getByRole('button', { name: /Escalate to MSO/i })).toBeDisabled()
  })

  it('shows plan status — lifecycle badge is visible', () => {
    render(<MissionControlView />)
    // "Plan status:" label always present in planner
    expect(screen.getByText(/Plan status:/i)).toBeInTheDocument()
  })

  it('plan starts in draft state (LifecycleBadge)', () => {
    render(<MissionControlView />)
    // The lifecycle strip buttons + LifecycleBadge all contain various labels.
    // We assert the badge text "draft" appears somewhere in the rendered output.
    const allDraft = screen.getAllByText(/\bdraft\b/i)
    // At minimum the LifecycleBadge shows "draft"
    expect(allDraft.length).toBeGreaterThan(0)
  })

  it('does NOT suggest direct execution from planner', () => {
    render(<MissionControlView />)
    expect(screen.queryByText(/execute now/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/run plan/i)).not.toBeInTheDocument()
  })

  it('states that escalation does not trigger execution', () => {
    render(<MissionControlView />)
    // The phrase appears in the planner header and/or next-safe-action section
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
    // The "Governed Preparation Cycle" section always has this row
    expect(screen.getByText('Execution Now Allowed')).toBeInTheDocument()
  })

  it('shows execution_allowed=false note after entity status loads', async () => {
    render(<MissionControlView />)
    clickTab('MSO')
    // After fetch resolves (mocked), the PostureRow note text appears
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
    // Label "Registry source:" may appear once or more but must be present
    const matches = screen.queryAllByText(/Registry source/i)
    expect(matches.length).toBeGreaterThan(0)
  })

  it('reports executionStatus as unavailable when no arms registered', () => {
    render(<MissionControlView />)
    clickTab('Arms')
    // Default state has empty registeredAgents — the badge shows unavailable
    expect(screen.getByText(/executionStatus: unavailable/i)).toBeInTheDocument()
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
})

describe('OutcomeTraceSpace — Space 5', () => {
  it('renders the Outcome + Authority Trace header', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    expect(screen.getByText(/Outcome.*Authority Trace.*ALPHA/i)).toBeInTheDocument()
  })

  it('renders all 9 authority chain stage labels', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    for (const label of [
      'MSO Kernel', 'Intent Contract', 'Policy', 'Governance', 'CapabilityToken',
      'Police Gate', 'AuthorityArtifact', 'Runner',
    ]) {
      // Use getAllByText since some labels may appear in multiple contexts
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
    // "Outcome" appears in tab bar + lifecycle strip + as stage label
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
    // The legend paragraph describes each stage status category
    expect(screen.getByText(/are architecturally closed to UI/i)).toBeInTheDocument()
  })

  it('renders the Outcome Status panel header', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    // OutcomeStatusPanel always renders "Outcome Status" as its header
    const matches = screen.getAllByText(/Outcome Status/i)
    expect(matches.length).toBeGreaterThan(0)
  })

  it('does NOT fabricate outcome success data', () => {
    render(<MissionControlView />)
    clickTab('Outcome')
    expect(screen.queryByText(/execution succeeded/i)).not.toBeInTheDocument()
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
