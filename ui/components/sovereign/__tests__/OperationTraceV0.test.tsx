import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OperationTraceV0 } from '../OperationTraceV0'
import type { OperationTraceV0 as OperationTraceV0Type } from '@/lib/types'

const FULL_TRACE: OperationTraceV0Type = {
  trace_version: 'v0',
  entry_id: 'entry-001',
  action_id: 'action-001',
  steps: [
    { step: 'prepared_action',    status: 'complete',          label: 'Prepared Action',       description: 'CODE: CODE_REVIEW', completed: true  },
    { step: 'human_confirmation', status: 'complete',          label: 'Human Confirmation',    description: 'Operator confirmed.', completed: true  },
    { step: 'policy_review',      status: 'complete',          label: 'Policy Review',         description: 'Capability policy approved (outcome=approved).', completed: true  },
    { step: 'authority_binding',  status: 'complete',          label: 'Authority Binding Draft', description: 'MSOAuthorityBindingDraft created.', completed: true  },
    { step: 'police_readiness',   status: 'draft_complete',    label: 'Police Readiness',      description: 'MSO draft chain complete.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution',             description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['CapabilityToken', 'OperationBinding'],
  blocking_reasons: ['Downstream not implemented.'],
  next_safe_step: 'Authority chain draft is complete.',
  execution_allowed: false,
  can_execute_now: false,
  used_execution: false,
}

const PENDING_TRACE: OperationTraceV0Type = {
  trace_version: 'v0',
  entry_id: 'entry-002',
  action_id: 'action-002',
  steps: [
    { step: 'prepared_action',    status: 'complete', label: 'Prepared Action',    description: 'CODE: CODE_REVIEW', completed: true  },
    { step: 'human_confirmation', status: 'pending',  label: 'Human Confirmation', description: 'Awaiting operator confirmation.', completed: false },
    { step: 'policy_review',      status: 'missing',  label: 'Policy Review',      description: 'Not yet reached.', completed: false },
    { step: 'authority_binding',  status: 'missing',  label: 'Authority Binding Draft', description: 'Not yet reached.', completed: false },
    { step: 'police_readiness',   status: 'not_ready', label: 'Police Readiness', description: 'Authority chain prerequisites not yet met.', completed: false },
    { step: 'execution',          status: 'blocked_by_design', label: 'Execution', description: 'Execution is closed by design.', completed: false },
  ],
  missing_requirements: ['human_confirmation'],
  blocking_reasons: ['No human confirmation record found.'],
  next_safe_step: 'POST /mso/prepared-actions/confirm with confirmed=true.',
  execution_allowed: false,
  can_execute_now: false,
  used_execution: false,
}

describe('OperationTraceV0', () => {
  // Scenario 1: no trace data → shows "Trace unavailable"
  describe('when trace is undefined', () => {
    it('renders Trace unavailable', () => {
      render(<OperationTraceV0 trace={undefined} />)
      expect(screen.getByText(/trace unavailable/i)).toBeInTheDocument()
    })

    it('renders Operation Trace header', () => {
      render(<OperationTraceV0 trace={undefined} />)
      expect(screen.getByText(/operation trace/i)).toBeInTheDocument()
    })
  })

  describe('when trace has empty steps', () => {
    it('renders Trace unavailable', () => {
      const emptyTrace: OperationTraceV0Type = {
        ...FULL_TRACE,
        steps: [],
      }
      render(<OperationTraceV0 trace={emptyTrace} />)
      expect(screen.getByText(/trace unavailable/i)).toBeInTheDocument()
    })
  })

  // Scenario 2: full trace renders all 6 steps
  describe('when full trace is provided', () => {
    it('renders all 6 step labels', () => {
      render(<OperationTraceV0 trace={FULL_TRACE} />)
      expect(screen.getByText('Prepared Action')).toBeInTheDocument()
      expect(screen.getByText('Human Confirmation')).toBeInTheDocument()
      expect(screen.getByText('Policy Review')).toBeInTheDocument()
      expect(screen.getByText('Authority Binding Draft')).toBeInTheDocument()
      expect(screen.getByText('Police Readiness')).toBeInTheDocument()
      expect(screen.getByText('Execution')).toBeInTheDocument()
    })

    it('renders step status tokens', () => {
      render(<OperationTraceV0 trace={FULL_TRACE} />)
      expect(screen.getAllByText(/— complete/).length).toBeGreaterThan(0)
      expect(screen.getByText(/— draft_complete/)).toBeInTheDocument()
      expect(screen.getByText(/— blocked_by_design/)).toBeInTheDocument()
    })
  })

  // Scenario 3: status dot classes applied correctly
  describe('status rendering', () => {
    it('shows pending status for human_confirmation when awaiting', () => {
      render(<OperationTraceV0 trace={PENDING_TRACE} />)
      expect(screen.getByText(/— pending/)).toBeInTheDocument()
    })

    it('shows missing status for unreached steps', () => {
      render(<OperationTraceV0 trace={PENDING_TRACE} />)
      expect(screen.getAllByText(/— missing/).length).toBeGreaterThanOrEqual(2)
    })

    it('renders step descriptions', () => {
      render(<OperationTraceV0 trace={PENDING_TRACE} />)
      expect(screen.getByText('Awaiting operator confirmation.')).toBeInTheDocument()
    })
  })

  // Scenario 4: next_safe_step rendered when present
  describe('next_safe_step', () => {
    it('renders next_safe_step text when provided', () => {
      render(<OperationTraceV0 trace={FULL_TRACE} />)
      expect(screen.getByText('Authority chain draft is complete.')).toBeInTheDocument()
    })

    it('renders next_safe_step for pending trace', () => {
      render(<OperationTraceV0 trace={PENDING_TRACE} />)
      expect(screen.getByText(/POST \/mso\/prepared-actions\/confirm/)).toBeInTheDocument()
    })

    it('does not render next_safe_step section when empty', () => {
      const noStep: OperationTraceV0Type = { ...FULL_TRACE, next_safe_step: '' }
      render(<OperationTraceV0 trace={noStep} />)
      expect(screen.queryByText('Authority chain draft is complete.')).not.toBeInTheDocument()
    })
  })
})
