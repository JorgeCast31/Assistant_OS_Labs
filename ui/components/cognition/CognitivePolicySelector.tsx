'use client'

/**
 * M29: CognitivePolicySelector
 *
 * Lets the operator choose the cognitive usage policy.
 * Changes are sent to the backend via POST /api/cognition/preferences.
 *
 * Rules:
 * - All options are bounded — none bypass the kernel.
 * - "deterministic_only" is always available (fail-safe).
 * - Never exposes raw prompt text or model invocation.
 */
import { useState } from 'react'
import { useCognitionStore } from '@/stores/cognition-store'
import type { CognitionPolicy } from '@/lib/types'

const POLICY_OPTIONS: { value: CognitionPolicy; label: string; description: string }[] = [
  {
    value:       'auto',
    label:       'Auto',
    description: 'System decides when to consult the local engine',
  },
  {
    value:       'prefer_local',
    label:       'Prefer local',
    description: 'Use local engine for advisory tasks when available',
  },
  {
    value:       'deterministic_only',
    label:       'Deterministic only',
    description: 'Never consult the local engine — deterministic path only',
  },
]

export function CognitivePolicySelector() {
  const uiEnabled  = useCognitionStore((s) => s.uiEnabled)
  const policy     = useCognitionStore((s) => s.policy)
  const policySetBy = useCognitionStore((s) => s.policySetBy)
  const setPolicy  = useCognitionStore((s) => s.setPolicy)
  const setPolicySetBy = useCognitionStore((s) => s.setPolicySetBy)

  const [saving,   setSaving]   = useState(false)
  const [saveErr,  setSaveErr]  = useState<string | null>(null)

  if (!uiEnabled) return null

  async function handleSelect(next: CognitionPolicy) {
    if (next === policy || saving) return
    setSaving(true)
    setSaveErr(null)
    try {
      const res = await fetch('/api/cognition/preferences', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ policy: next }),
      })
      const data = await res.json() as { ok: boolean; error?: string; policy?: CognitionPolicy }
      if (!data.ok) {
        setSaveErr(data.error ?? 'Failed to save policy')
        return
      }
      setPolicy(data.policy ?? next)
      setPolicySetBy('user')
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : 'Network error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h3 className="text-[11px] font-mono font-medium text-tx-secondary uppercase tracking-wider">
          Cognitive Policy
        </h3>
        {policySetBy === 'user' && (
          <span className="text-[9px] font-mono text-tx-muted">(user-set)</span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        {POLICY_OPTIONS.map((opt) => {
          const selected = policy === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => handleSelect(opt.value)}
              disabled={saving}
              className={[
                'flex items-start gap-3 w-full px-3 py-2 rounded border text-left transition-colors',
                selected
                  ? 'border-accent bg-accent/10 text-tx-primary'
                  : 'border-os-border bg-os-surface text-tx-muted hover:border-os-border-hi hover:text-tx-secondary',
                saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
              ].join(' ')}
            >
              {/* Radio dot */}
              <span
                className={[
                  'mt-0.5 w-3 h-3 rounded-full border flex-shrink-0 transition-colors',
                  selected ? 'border-accent bg-accent' : 'border-tx-muted',
                ].join(' ')}
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-[11px] font-mono font-medium">{opt.label}</span>
                <span className="text-[10px] font-mono">{opt.description}</span>
              </span>
            </button>
          )
        })}
      </div>

      {saveErr && (
        <p className="text-[10px] font-mono text-err px-1">{saveErr}</p>
      )}
    </div>
  )
}
