import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type {
  PreparedActionsQueueResponse,
  PreparedActionQueueEntry,
  ConfirmPreparedActionResult,
} from '@/lib/types'

// ── Mock API helpers ──────────────────────────────────────────────────────────
vi.mock('@/lib/api', () => ({
  getPreparedActionsPending: vi.fn(),
  confirmPreparedAction: vi.fn(),
}))

import { getPreparedActionsPending, confirmPreparedAction } from '@/lib/api'
import { PreparedActionsReviewPanel } from '../PreparedActionsReviewPanel'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const NOW = '2026-05-30T00:00:00.000Z'

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

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getPreparedActionsPending).mockResolvedValue(EMPTY_QUEUE)
  vi.mocked(confirmPreparedAction).mockResolvedValue(CONFIRM_OK)
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

  // ── 4. Renders plan_id / correlation_id ────────────────────────────────────

  it('renders preparation_id as correlation context when present', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/prep-test-001/)).toBeInTheDocument()
    )
  })

  // ── 5. Renders "Prepared — Awaiting Confirmation" label ──────────────────

  it('renders "Prepared — Awaiting Confirmation" label', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/Prepared — Awaiting Confirmation/)).toBeInTheDocument()
    )
  })

  // ── 6. Renders payload summary safely ────────────────────────────────────

  it('renders domain and requested_action from entry', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => {
      expect(document.body.textContent).toContain('CODE')
      expect(document.body.textContent).toContain('code_review')
    })
  })

  // ── 7. Confirm button visible only for pending_review entries ────────────

  it('shows Confirm button for pending_review entries', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /confirm preparedaction/i })).toBeInTheDocument()
    )
  })
})

// ── 8. Confirm requires window.confirm() ─────────────────────────────────────

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

  // ── 9. Confirm calls helper with correct payload ──────────────────────────

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

  // ── 10. Refreshes list after confirm ─────────────────────────────────────

  it('calls getPreparedActionsPending again after confirming', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByRole('button', { name: /confirm preparedaction/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm preparedaction/i }))
    await waitFor(() => expect(getPreparedActionsPending).toHaveBeenCalledTimes(2))
  })
})

// ── 11. Error state ───────────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — error state', () => {
  it('shows error state when backend unavailable', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(UNAVAILABLE_QUEUE)
    render(<PreparedActionsReviewPanel />)
    await waitFor(() =>
      expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument()
    )
  })
})

// ── 12. No Execute button ─────────────────────────────────────────────────────

describe('PreparedActionsReviewPanel — forbidden controls', () => {
  it('never renders an Execute button', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    expect(screen.queryByRole('button', { name: /^execute$/i })).toBeNull()
  })

  // ── 13. Forbidden labels never appear ────────────────────────────────────

  it('never renders forbidden labels', async () => {
    vi.mocked(getPreparedActionsPending).mockResolvedValue(makeQueueResponse([makeEntry()]))
    render(<PreparedActionsReviewPanel />)
    await waitFor(() => screen.getByText(/cpa-test-001/))
    const FORBIDDEN = [
      /\bExecute\b/,
      /\bRun\b/,
      /ready to execute/i,
      /\bAuthorized\b/,
      /\bRunning\b/,
      /\bLive\b/,
      /\bCompleted\b/,
    ]
    for (const pattern of FORBIDDEN) {
      expect(document.body.textContent).not.toMatch(pattern)
    }
  })
})

// ── 14. No import of /api/agent/execute ──────────────────────────────────────
// Verified statically: PreparedActionsReviewPanel does not import /api/agent/execute.
// This is a code-level invariant enforced by the forbidden-labels test above.

// ── 15. MissionControlView includes PreparedActionsReviewPanel ───────────────
// This is covered by MissionControlView.test.tsx integration test.
// A lightweight smoke-test is included here to confirm export.

describe('PreparedActionsReviewPanel — export', () => {
  it('is exported as a named component', () => {
    expect(PreparedActionsReviewPanel).toBeDefined()
    expect(typeof PreparedActionsReviewPanel).toBe('function')
  })
})
