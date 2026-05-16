'use client'

import { useMSOChatStore } from '@/stores/mso-chat-store'
import type { MSOAgentSeat, MSOInteractionMode, MSOCognitionTier } from '@/lib/sovereign/types'

const SEATS: { value: MSOAgentSeat; label: string }[] = [
  { value: 'mso', label: 'MSO' },
  { value: 'system_assistant', label: 'System' },
  { value: 'machine_operator', label: 'MachOp' },
  { value: 'code', label: 'CODE' },
  { value: 'work', label: 'WORK' },
  { value: 'fin', label: 'FIN' },
]

const MODES: { value: MSOInteractionMode; label: string; note: string }[] = [
  { value: 'conversational', label: 'Conversational', note: 'Cognitive chat with grounding' },
  { value: 'planning', label: 'Planning', note: 'Prepare governed action — no execution' },
  { value: 'validation', label: 'Validation', note: 'Read queue/state — strictly read-only' },
  { value: 'orchestration', label: 'Orchestration', note: 'Governed-entry narrative — no runner' },
]

const TIERS: { value: MSOCognitionTier; label: string }[] = [
  { value: 'economic', label: 'Economic' },
  { value: 'advanced', label: 'Advanced' },
]

function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: T; label: string; note?: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[9px] font-mono text-tx-muted uppercase tracking-widest w-14 shrink-0">
        {label}
      </span>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          aria-pressed={value === o.value}
          title={o.note}
          className={`px-2 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border transition-colors ${
            value === o.value
              ? 'border-accent text-accent bg-accent/10'
              : 'border-os-border text-tx-muted bg-os-base hover:text-tx-secondary hover:border-os-border/60'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function MSOInteractionModeSelector() {
  const { agentSeat, interactionMode, cognitionTier, setAgentSeat, setInteractionMode, setCognitionTier } =
    useMSOChatStore()

  return (
    <div className="flex flex-col gap-1 pb-2 border-b border-os-border/40">
      <ChipGroup label="Seat" options={SEATS} value={agentSeat} onChange={setAgentSeat} />
      <ChipGroup label="Mode" options={MODES} value={interactionMode} onChange={setInteractionMode} />
      <ChipGroup label="Cognition" options={TIERS} value={cognitionTier} onChange={setCognitionTier} />
    </div>
  )
}
