import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MSOChatTranscript } from '../MSOChatTranscript'
import type { SovereignMessage } from '@/lib/sovereign/types'

function makeMsg(overrides: Partial<SovereignMessage> = {}): SovereignMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content: 'hello',
    timestamp: '2026-01-01T00:00:00.000Z',
    surface: 'mso_direct',
    ...overrides,
  }
}

describe('MSOChatTranscript', () => {
  it('renders empty state when no messages', () => {
    render(<MSOChatTranscript messages={[]} />)
    expect(screen.getByText(/no messages|start|send/i)).toBeInTheDocument()
  })

  it('renders user message content', () => {
    const msg = makeMsg({ content: 'What is the system status?' })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.getByText('What is the system status?')).toBeInTheDocument()
  })

  it('renders assistant message content', () => {
    const msg = makeMsg({ role: 'assistant', content: 'System is NORMAL.' })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.getByText('System is NORMAL.')).toBeInTheDocument()
  })

  it('renders the role label', () => {
    render(<MSOChatTranscript messages={[makeMsg({ role: 'user' })]} />)
    expect(screen.getByText(/user/i)).toBeInTheDocument()
  })

  it('does NOT render execution_status badge when field is absent', () => {
    const msg = makeMsg({ role: 'assistant' })
    render(<MSOChatTranscript messages={[msg]} />)
    // Badge text is never inferred — absent means no badge
    expect(screen.queryByText(/real|stub|unavailable|partial/i)).not.toBeInTheDocument()
  })

  it('renders execution_status badge when field is present', () => {
    const msg = makeMsg({ role: 'assistant', executionStatus: 'unavailable' })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument()
  })

  it('renders execution_status=real when explicitly set', () => {
    const msg = makeMsg({ role: 'assistant', executionStatus: 'real' })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.getByText(/real/i)).toBeInTheDocument()
  })

  it('does NOT render governance_trace badge when field is absent', () => {
    const msg = makeMsg({ role: 'assistant' })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.queryByText(/ALLOW|BLOCK|REQUIRE_CONFIRMATION|DEGRADED/)).not.toBeInTheDocument()
  })

  it('renders governance_trace decision when present', () => {
    const msg = makeMsg({
      role: 'assistant',
      governanceTrace: { decision: 'ALLOW', risk_level: 'low' },
    })
    render(<MSOChatTranscript messages={[msg]} />)
    expect(screen.getByText(/ALLOW/)).toBeInTheDocument()
  })

  it('renders multiple messages in order', () => {
    const msgs = [
      makeMsg({ id: 'a', content: 'first message' }),
      makeMsg({ id: 'b', content: 'second message', role: 'assistant' }),
    ]
    render(<MSOChatTranscript messages={msgs} />)
    const items = screen.getAllByText(/first message|second message/)
    expect(items[0].textContent).toBe('first message')
    expect(items[1].textContent).toBe('second message')
  })
})
