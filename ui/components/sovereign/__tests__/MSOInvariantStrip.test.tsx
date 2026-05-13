import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MSOInvariantStrip } from '../MSOInvariantStrip'

describe('MSOInvariantStrip', () => {
  it('renders execution_allowed=false', () => {
    render(<MSOInvariantStrip />)
    expect(screen.getByText(/execution_allowed.*false/i)).toBeInTheDocument()
  })

  it('renders can_execute_now=false', () => {
    render(<MSOInvariantStrip />)
    expect(screen.getByText(/can_execute_now.*false/i)).toBeInTheDocument()
  })

  it('renders the mso_direct surface label', () => {
    render(<MSOInvariantStrip />)
    expect(screen.getByText(/mso_direct/i)).toBeInTheDocument()
  })

  it('renders the non-execution statement', () => {
    render(<MSOInvariantStrip />)
    expect(screen.getByText(/coordinates.*does not execute/i)).toBeInTheDocument()
  })

  it('has no dismiss button', () => {
    render(<MSOInvariantStrip />)
    expect(screen.queryByRole('button', { name: /close|dismiss|x/i })).not.toBeInTheDocument()
  })
})
