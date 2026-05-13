import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MSOProviderSelector } from '../MSOProviderSelector'
import { useSeatProviderStore } from '@/stores/seat-provider-store'
import type { MSOSeatProviderResponse } from '@/lib/types'

function makeProviderResponse(overrides: Partial<MSOSeatProviderResponse> = {}): MSOSeatProviderResponse {
  return {
    ok: true,
    seat_provider: {
      provider_name: 'anthropic',
      model_name: 'claude-sonnet-4-6',
      provider_kind: 'remote',
      is_available: true,
      availability: 'available',
      local_or_remote: 'remote',
      cognitive_only: true,
      used_execution: false,
      non_executing: true,
    },
    description: 'Anthropic provider seated.',
    execution_allowed: false,
    can_execute_now: false,
    note: 'Cognitive only.',
    ...overrides,
  }
}

describe('MSOProviderSelector', () => {
  beforeEach(() => {
    useSeatProviderStore.setState({ seatProvider: null, pollError: null })
  })

  it('shows loading state when no provider data', () => {
    render(<MSOProviderSelector />)
    expect(screen.getByText(/polling|loading|no provider/i)).toBeInTheDocument()
  })

  it('renders provider name when provider is seated', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    // Multiple elements may show "anthropic" — just verify at least one exists
    expect(screen.getAllByText(/anthropic/i).length).toBeGreaterThan(0)
  })

  it('renders model name when provider is seated', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    expect(screen.getByText(/claude-sonnet-4-6/i)).toBeInTheDocument()
  })

  it('renders availability status', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    // At least one element shows the word "available"
    expect(screen.getAllByText(/available/i).length).toBeGreaterThan(0)
  })

  it('renders local_or_remote deployment', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    expect(screen.getAllByText(/remote/i).length).toBeGreaterThan(0)
  })

  it('shows all four provider options: llama, anthropic, openai, gemma', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    expect(screen.getAllByText(/llama/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/anthropic/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/openai|gpt/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/gemma/i).length).toBeGreaterThan(0)
  })

  it('shows read-only notice with MSO_SEAT_PROVIDER instruction', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    // Bottom notice: "Provider selection is read-only in v0. Change MSO_SEAT_PROVIDER..."
    expect(screen.getAllByText(/read-only/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/MSO_SEAT_PROVIDER/i).length).toBeGreaterThan(0)
  })

  it('shows not-configured state when seat_provider is null', () => {
    useSeatProviderStore.setState({
      seatProvider: makeProviderResponse({ seat_provider: null }),
    })
    render(<MSOProviderSelector />)
    expect(screen.getByText(/not configured/i)).toBeInTheDocument()
  })

  it('provider options are not interactive in v0 (no enabled select/radio)', () => {
    useSeatProviderStore.setState({ seatProvider: makeProviderResponse() })
    render(<MSOProviderSelector />)
    const selects = screen.queryAllByRole('combobox')
    const radios = screen.queryAllByRole('radio')
    const enabledInteractives = [...selects, ...radios].filter(
      (el) => !(el as HTMLInputElement).disabled
    )
    expect(enabledInteractives).toHaveLength(0)
  })
})
