import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MSOComposer } from '../MSOComposer'
import { useMSOChatStore } from '@/stores/mso-chat-store'

// Mock sendSovereignMessage — intercept the call, verify surface, return a stub response
vi.mock('@/lib/sovereign/api', () => ({
  sendSovereignMessage: vi.fn(),
}))

import { sendSovereignMessage } from '@/lib/sovereign/api'
const mockSend = sendSovereignMessage as ReturnType<typeof vi.fn>

describe('MSOComposer', () => {
  beforeEach(() => {
    useMSOChatStore.getState().resetTranscript()
    mockSend.mockReset()
    mockSend.mockResolvedValue({
      ok: true,
      message: 'Acknowledged.',
      trace_id: 'trace-1',
      needs_confirmation: false,
    })
  })

  it('renders textarea and send button', () => {
    render(<MSOComposer />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument()
  })

  it('calls sendSovereignMessage with surface="mso_direct"', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'hello mso')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(mockSend).toHaveBeenCalled())
    const [, surface] = mockSend.mock.calls[0]
    expect(surface).toBe('mso_direct')
  })

  it('never calls sendSovereignMessage with surface="assistant_chat"', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'test message')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(mockSend).toHaveBeenCalled())
    for (const call of mockSend.mock.calls) {
      expect(call[1]).not.toBe('assistant_chat')
    }
  })

  it('passes user text as first argument to sendSovereignMessage', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'system status?')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(mockSend).toHaveBeenCalled())
    expect(mockSend.mock.calls[0][0]).toBe('system status?')
  })

  it('appends user message to the store on submit', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'test input')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(mockSend).toHaveBeenCalled())
    const { messages } = useMSOChatStore.getState()
    expect(messages.some((m) => m.role === 'user' && m.content === 'test input')).toBe(true)
  })

  it('appends assistant response to the store', async () => {
    const user = userEvent.setup()
    mockSend.mockResolvedValue({
      ok: true,
      message: 'Response from MSO.',
      trace_id: 'trace-x',
      needs_confirmation: false,
    })
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'query')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => {
      const { messages } = useMSOChatStore.getState()
      expect(messages.some((m) => m.role === 'assistant' && m.content === 'Response from MSO.')).toBe(true)
    })
  })

  it('send button is disabled while loading', async () => {
    let resolveResponse!: () => void
    mockSend.mockReturnValue(new Promise<{ ok: boolean; message: string; trace_id: string; needs_confirmation: boolean }>((resolve) => { resolveResponse = () => resolve({ ok: true, message: 'ok', trace_id: '', needs_confirmation: false }) }))
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'slow')
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
    resolveResponse()
  })

  it('clears textarea after submit', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    const textarea = screen.getByRole('textbox')
    await user.type(textarea, 'clear me')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => expect(mockSend).toHaveBeenCalled())
    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe(''))
  })

  it('does not submit on empty text', async () => {
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(mockSend).not.toHaveBeenCalled()
  })

  it('sets execution_status=unavailable on error response', async () => {
    mockSend.mockResolvedValue({
      ok: false,
      message: 'Backend error.',
      trace_id: '',
      needs_confirmation: false,
      execution_status: 'unavailable',
      execution_status_source: 'ui_fallback',
    })
    const user = userEvent.setup()
    render(<MSOComposer />)
    await user.type(screen.getByRole('textbox'), 'failing query')
    await user.click(screen.getByRole('button', { name: /send/i }))
    await waitFor(() => {
      const { messages } = useMSOChatStore.getState()
      const errMsg = messages.find((m) => m.role === 'assistant')
      expect(errMsg?.executionStatus).toBe('unavailable')
    })
  })
})
