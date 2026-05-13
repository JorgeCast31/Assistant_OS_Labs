'use client'

import { useSeatProviderStore } from '@/stores/seat-provider-store'

const PROVIDER_OPTIONS = ['llama', 'anthropic', 'openai/gpt', 'gemma'] as const

function availabilityTone(availability: string, isAvailable: boolean): string {
  if (isAvailable) return 'text-ok border-ok/30 bg-ok/10'
  if (availability === 'api_key_missing' || availability === 'unavailable') return 'text-warn border-warn/30 bg-warn/10'
  return 'text-tx-muted border-os-border bg-os-base'
}

export function MSOProviderSelector() {
  const seatProvider = useSeatProviderStore((s) => s.seatProvider)
  const pollError = useSeatProviderStore((s) => s.pollError)

  if (!seatProvider) {
    return (
      <div className="rounded-lg border border-os-border bg-os-surface p-3">
        <p className="text-xs font-mono text-tx-muted">Polling provider metadata…</p>
      </div>
    )
  }

  const provider = seatProvider.seat_provider

  return (
    <div className="space-y-3 rounded-lg border border-os-border bg-os-surface p-4">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
          Cognitive Seat Provider
        </p>
        <span className="text-[10px] font-mono text-tx-muted px-2 py-0.5 rounded border border-os-border bg-os-base">
          v0 · read-only
        </span>
      </div>

      {pollError && (
        <p className="text-[10px] font-mono text-warn">Poll error: {pollError}</p>
      )}

      {provider === null ? (
        <p className="text-xs font-mono text-tx-muted">
          Not configured. Set <code className="text-accent">MSO_SEAT_PROVIDER</code> env var.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-2 text-[10px] font-mono">
          <div>
            <p className="text-tx-muted mb-0.5">Provider</p>
            <p className="text-tx-primary font-medium">{provider.provider_name}</p>
          </div>
          <div>
            <p className="text-tx-muted mb-0.5">Model</p>
            <p className="text-tx-primary">{provider.model_name || '—'}</p>
          </div>
          <div>
            <p className="text-tx-muted mb-0.5">Availability</p>
            <span className={`inline-block px-1.5 py-0.5 rounded border text-[9px] uppercase tracking-wider ${availabilityTone(provider.availability, provider.is_available)}`}>
              {provider.availability}
            </span>
          </div>
          <div>
            <p className="text-tx-muted mb-0.5">Deployment</p>
            <p className="text-tx-secondary">{provider.local_or_remote}</p>
          </div>
        </div>
      )}

      <div>
        <p className="text-[10px] font-mono text-tx-muted mb-2">Available providers</p>
        <div className="flex flex-wrap gap-2">
          {PROVIDER_OPTIONS.map((name) => {
            const isSeated = provider?.provider_name?.toLowerCase() === name.split('/')[0]
            return (
              <span
                key={name}
                className={`px-2 py-1 rounded border text-[10px] font-mono cursor-not-allowed select-none ${
                  isSeated
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-os-border bg-os-base text-tx-muted'
                }`}
                title="Provider selection is read-only in v0"
              >
                {name}
                {isSeated && <span className="ml-1 text-[9px]">← seated</span>}
              </span>
            )
          })}
        </div>
      </div>

      <p className="text-[10px] font-mono text-tx-muted border-t border-os-border pt-2">
        Provider selection is read-only in v0. Change{' '}
        <code className="text-accent">MSO_SEAT_PROVIDER</code> and restart backend to switch providers.
      </p>
    </div>
  )
}
