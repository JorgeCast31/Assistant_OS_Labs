import { describe, it, expect, beforeEach } from 'vitest'
import { useMSOChatStore } from '../mso-chat-store'
import type { SovereignMessage } from '@/lib/sovereign/types'

function makeMessage(overrides: Partial<SovereignMessage> = {}): SovereignMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content: 'test message',
    timestamp: '2026-01-01T00:00:00.000Z',
    surface: 'mso_direct',
    ...overrides,
  }
}

describe('useMSOChatStore', () => {
  beforeEach(() => {
    useMSOChatStore.getState().resetTranscript()
  })

  it('starts with empty messages and isLoading=false', () => {
    const { messages, isLoading } = useMSOChatStore.getState()
    expect(messages).toEqual([])
    expect(isLoading).toBe(false)
  })

  it('appendMessage adds a message to the transcript', () => {
    const msg = makeMessage()
    useMSOChatStore.getState().appendMessage(msg)
    expect(useMSOChatStore.getState().messages).toHaveLength(1)
    expect(useMSOChatStore.getState().messages[0]).toEqual(msg)
  })

  it('appendMessage adds multiple messages in order', () => {
    const msg1 = makeMessage({ id: 'a', content: 'first' })
    const msg2 = makeMessage({ id: 'b', content: 'second', role: 'assistant' })
    useMSOChatStore.getState().appendMessage(msg1)
    useMSOChatStore.getState().appendMessage(msg2)
    const { messages } = useMSOChatStore.getState()
    expect(messages).toHaveLength(2)
    expect(messages[0].id).toBe('a')
    expect(messages[1].id).toBe('b')
  })

  it('updateMessage patches a message by id', () => {
    const msg = makeMessage({ id: 'x', content: 'original' })
    useMSOChatStore.getState().appendMessage(msg)
    useMSOChatStore.getState().updateMessage('x', { content: 'updated' })
    expect(useMSOChatStore.getState().messages[0].content).toBe('updated')
  })

  it('updateMessage does not affect other messages', () => {
    useMSOChatStore.getState().appendMessage(makeMessage({ id: 'a', content: 'A' }))
    useMSOChatStore.getState().appendMessage(makeMessage({ id: 'b', content: 'B' }))
    useMSOChatStore.getState().updateMessage('a', { content: 'A-updated' })
    expect(useMSOChatStore.getState().messages[1].content).toBe('B')
  })

  it('setLoading sets isLoading to true', () => {
    useMSOChatStore.getState().setLoading(true)
    expect(useMSOChatStore.getState().isLoading).toBe(true)
  })

  it('setLoading sets isLoading to false', () => {
    useMSOChatStore.getState().setLoading(true)
    useMSOChatStore.getState().setLoading(false)
    expect(useMSOChatStore.getState().isLoading).toBe(false)
  })

  it('resetTranscript clears messages and resets isLoading', () => {
    useMSOChatStore.getState().appendMessage(makeMessage())
    useMSOChatStore.getState().setLoading(true)
    useMSOChatStore.getState().resetTranscript()
    expect(useMSOChatStore.getState().messages).toEqual([])
    expect(useMSOChatStore.getState().isLoading).toBe(false)
  })
})
