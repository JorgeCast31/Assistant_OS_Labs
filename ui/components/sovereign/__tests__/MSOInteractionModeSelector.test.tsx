import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MSOInteractionModeSelector } from '../MSOInteractionModeSelector'
import { useMSOChatStore } from '@/stores/mso-chat-store'

describe('MSOInteractionModeSelector', () => {
  beforeEach(() => {
    // Reset to defaults before each test
    useMSOChatStore.setState({
      agentSeat: 'mso',
      interactionMode: 'conversational',
      cognitionTier: 'economic',
    })
  })

  // ── Mode buttons ──────────────────────────────────────────────────────────

  it('renders all four interaction mode buttons', () => {
    render(<MSOInteractionModeSelector />)
    expect(screen.getByRole('button', { name: /conversational/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /planning/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /validation/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /orchestration/i })).toBeInTheDocument()
  })

  it('default mode is conversational (aria-pressed=true)', () => {
    render(<MSOInteractionModeSelector />)
    const btn = screen.getByRole('button', { name: /conversational/i })
    expect(btn).toHaveAttribute('aria-pressed', 'true')
  })

  it('other modes are aria-pressed=false by default', () => {
    render(<MSOInteractionModeSelector />)
    expect(screen.getByRole('button', { name: /planning/i })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: /validation/i })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: /orchestration/i })).toHaveAttribute('aria-pressed', 'false')
  })

  it('clicking Planning calls setInteractionMode with planning', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /planning/i }))
    expect(useMSOChatStore.getState().interactionMode).toBe('planning')
  })

  it('clicking Validation calls setInteractionMode with validation', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /validation/i }))
    expect(useMSOChatStore.getState().interactionMode).toBe('validation')
  })

  it('clicking Orchestration calls setInteractionMode with orchestration', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /orchestration/i }))
    expect(useMSOChatStore.getState().interactionMode).toBe('orchestration')
  })

  it('selected mode button shows aria-pressed=true after click', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /planning/i }))
    expect(useMSOChatStore.getState().interactionMode).toBe('planning')
  })

  // ── Seat buttons ──────────────────────────────────────────────────────────

  it('renders MSO seat button', () => {
    render(<MSOInteractionModeSelector />)
    expect(screen.getByRole('button', { name: /^MSO$/i })).toBeInTheDocument()
  })

  it('default seat is mso (aria-pressed=true)', () => {
    render(<MSOInteractionModeSelector />)
    const btn = screen.getByRole('button', { name: /^MSO$/i })
    expect(btn).toHaveAttribute('aria-pressed', 'true')
  })

  it('clicking a seat updates agentSeat in store', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /^CODE$/i }))
    expect(useMSOChatStore.getState().agentSeat).toBe('code')
  })

  // ── Cognition tier buttons ────────────────────────────────────────────────

  it('renders Economic and Advanced cognition buttons', () => {
    render(<MSOInteractionModeSelector />)
    expect(screen.getByRole('button', { name: /economic/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /advanced/i })).toBeInTheDocument()
  })

  it('default cognition tier is economic (aria-pressed=true)', () => {
    render(<MSOInteractionModeSelector />)
    const btn = screen.getByRole('button', { name: /economic/i })
    expect(btn).toHaveAttribute('aria-pressed', 'true')
  })

  it('clicking Advanced updates cognitionTier in store', () => {
    render(<MSOInteractionModeSelector />)
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }))
    expect(useMSOChatStore.getState().cognitionTier).toBe('advanced')
  })
})
