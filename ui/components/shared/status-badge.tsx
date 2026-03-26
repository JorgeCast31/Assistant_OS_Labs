'use client'

import type { HealthStatus } from '@/lib/types'

/** All values the badge can display */
export type BadgeStatus = HealthStatus | 'idle'

const STATUS_STYLES: Record<string, string> = {
  ok:          'bg-ok/15 text-ok border-ok/30',
  warn:        'bg-warn/15 text-warn border-warn/30',
  degraded:    'bg-warn/15 text-warn border-warn/30',
  down:        'bg-err/15 text-err border-err/30',
  unknown:     'bg-idle/20 text-tx-secondary border-idle/30',
  idle:        'bg-idle/20 text-tx-secondary border-idle/30',
}

const DOT_STYLES: Record<string, string> = {
  ok:          'bg-ok animate-pulse-slow',
  warn:        'bg-warn animate-pulse-slow',
  degraded:    'bg-warn animate-pulse-slow',
  down:        'bg-err animate-pulse',
  unknown:     'bg-idle',
  idle:        'bg-idle',
}

const FALLBACK_STYLE    = STATUS_STYLES.unknown
const FALLBACK_DOT      = DOT_STYLES.unknown

interface StatusBadgeProps {
  status: BadgeStatus | string  // string allows mapped backend values passthrough
  label?: string
  dot?: boolean
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, label, dot = false, size = 'sm' }: StatusBadgeProps) {
  const text = label ?? status
  const base = size === 'sm'
    ? 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono border'
    : 'inline-flex items-center gap-2 px-2.5 py-1 rounded text-sm font-mono border'

  return (
    <span className={`${base} ${STATUS_STYLES[status] ?? FALLBACK_STYLE}`}>
      {dot && (
        <span className={`inline-block rounded-full flex-shrink-0 ${
          size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2'
        } ${DOT_STYLES[status] ?? FALLBACK_DOT}`} />
      )}
      {text}
    </span>
  )
}
