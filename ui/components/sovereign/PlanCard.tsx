'use client'

import type { MSOPlanItem } from '@/lib/sovereign/types'

// ── Status Colors ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<MSOPlanItem['status'], { bg: string; border: string; text: string; icon: string }> = {
  pending:   { bg: 'bg-slate-500/10',   border: 'border-slate-500/20', text: 'text-slate-400',   icon: '○' },
  executing: { bg: 'bg-amber-500/10',   border: 'border-amber-500/20', text: 'text-amber-400',   icon: '◐' },
  completed: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', text: 'text-emerald-400', icon: '●' },
  failed:    { bg: 'bg-red-500/10',     border: 'border-red-500/20',   text: 'text-red-400',     icon: '✕' },
  blocked:   { bg: 'bg-red-500/10',     border: 'border-red-500/20',   text: 'text-red-400',     icon: '⊘' },
}

// ── Plan Item ─────────────────────────────────────────────────────────────────

interface PlanItemRowProps {
  item: MSOPlanItem
  index: number
}

function PlanItemRow({ item, index }: PlanItemRowProps) {
  const style = STATUS_STYLES[item.status] ?? STATUS_STYLES.pending

  return (
    <div className={`flex items-start gap-3 px-3 py-2.5 ${style.bg} ${style.border} border rounded-lg`}>
      <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
        <span className={`text-xs font-mono ${style.text}`}>
          {style.icon}
        </span>
        <span className="text-[10px] font-mono text-tx-muted">
          #{index + 1}
        </span>
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono font-medium ${style.text}`}>
            {item.action}
          </span>
          {item.requiresAuth && (
            <span className="px-1.5 py-0.5 text-[8px] font-mono bg-amber-500/20 text-amber-400 rounded uppercase">
              Auth
            </span>
          )}
        </div>
        <p className="text-xs font-mono text-tx-secondary mt-0.5">
          {item.description}
        </p>
      </div>
      
      <span className={`text-[9px] font-mono ${style.text} uppercase flex-shrink-0`}>
        {item.status}
      </span>
    </div>
  )
}

// ── Plan Card ─────────────────────────────────────────────────────────────────

interface PlanCardProps {
  items: MSOPlanItem[]
  title?: string
}

export function PlanCard({ items, title = 'Execution Plan' }: PlanCardProps) {
  if (!items.length) return null

  const completedCount = items.filter(i => i.status === 'completed').length
  const failedCount = items.filter(i => i.status === 'failed' || i.status === 'blocked').length
  const executingCount = items.filter(i => i.status === 'executing').length

  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-amber-500/20 bg-amber-500/5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-amber-400">
              <path d="M7 1L12 4V10L7 13L2 10V4L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            </svg>
            <span className="text-xs font-mono font-medium text-amber-400">
              {title}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[10px] font-mono">
            {completedCount > 0 && (
              <span className="text-emerald-400">{completedCount} done</span>
            )}
            {executingCount > 0 && (
              <span className="text-amber-400 animate-pulse">{executingCount} running</span>
            )}
            {failedCount > 0 && (
              <span className="text-red-400">{failedCount} failed</span>
            )}
            <span className="text-tx-muted">{items.length} total</span>
          </div>
        </div>
      </div>

      {/* Items */}
      <div className="p-3 space-y-2">
        {items.map((item, i) => (
          <PlanItemRow key={item.id} item={item} index={i} />
        ))}
      </div>
    </div>
  )
}
