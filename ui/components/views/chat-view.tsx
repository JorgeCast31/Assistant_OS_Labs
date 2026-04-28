'use client'

import React, {
  useState, useRef, useEffect, useCallback,
  KeyboardEvent, Fragment,
  type ReactNode,
} from 'react'
import { ChatApiError, sendChatMessage, apiSearchMessages } from '@/lib/api'
import type { MessageSearchResult }           from '@/lib/api'
import { useUIStore }             from '@/stores/ui-store'
import { useChatSessionsStore }   from '@/stores/chat-sessions-store'
import type { ChatSession }       from '@/lib/chat-sessions'
import type {
  ChatMessage,
  ChatUIAction,
  ChatAction,
  PlanItem,
  SendChatRequest,
  GovernanceTrace,
  ExecutionStatus,
  ExecutionStatusSource,
} from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function genId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function executionStatusClass(status: ExecutionStatus): string {
  switch (status) {
    case 'real':
      return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
    case 'stub':
      return 'bg-amber-500/15 text-amber-300 border-amber-500/25'
    case 'partial':
      return 'bg-sky-500/15 text-sky-300 border-sky-500/25'
    case 'error':
      return 'bg-red-500/15 text-red-300 border-red-500/25'
    case 'unavailable':
      return 'bg-slate-500/15 text-slate-300 border-slate-500/25'
  }
}

function ExecutionStatusBadge({
  status,
  source = 'backend',
}: {
  status: ExecutionStatus
  source?: ExecutionStatusSource
}) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider ${executionStatusClass(status)}`}>
      execution_status: {status}{source === 'ui_fallback' ? ' (ui fallback)' : ''}
    </span>
  )
}

// ── RichText ──────────────────────────────────────────────────────────────────
//
// Lightweight inline renderer. No external library.
// Handles: code fences, bullet lists, inline code, paragraphs.

type RichBlock =
  | { t: 'para'; text: string }
  | { t: 'list'; items: string[] }
  | { t: 'code'; lang: string; src: string }

function parseBlocks(raw: string): RichBlock[] {
  const blocks: RichBlock[] = []
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = fenceRe.exec(raw)) !== null) {
    const before = raw.slice(last, m.index).trim()
    if (before) parseParagraphs(before, blocks)
    blocks.push({ t: 'code', lang: m[1] || 'text', src: m[2].trimEnd() })
    last = m.index + m[0].length
  }
  const tail = raw.slice(last).trim()
  if (tail) parseParagraphs(tail, blocks)
  return blocks.length ? blocks : [{ t: 'para', text: raw }]
}

function parseParagraphs(text: string, out: RichBlock[]) {
  const chunks = text.split(/\n{2,}/)
  for (const chunk of chunks) {
    const trimmed = chunk.trim()
    if (!trimmed) continue
    const lines = trimmed.split('\n')
    const isList = lines.every(l => /^[-•*]\s/.test(l))
    if (isList) {
      out.push({ t: 'list', items: lines.map(l => l.replace(/^[-•*]\s+/, '')) })
    } else {
      out.push({ t: 'para', text: trimmed })
    }
  }
}

function InlineText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('`') && part.endsWith('`') ? (
          <code key={i} className="px-1 py-0.5 rounded bg-os-elevated text-[11px] font-mono text-accent border border-os-border">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        )
      )}
    </>
  )
}

function RichText({ content }: { content: string }) {
  if (!content) return null
  try {
    const blocks = parseBlocks(content)
    return (
      <div className="space-y-2">
        {blocks.map((block, i) => {
          if (block.t === 'code') {
            return (
              <div key={i} className="rounded-lg overflow-hidden border border-os-border">
                {block.lang && block.lang !== 'text' && (
                  <div className="px-3 py-1 bg-os-elevated border-b border-os-border">
                    <span className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">{block.lang}</span>
                  </div>
                )}
                <pre className="px-3 py-2.5 overflow-x-auto bg-os-elevated text-xs font-mono text-tx-primary whitespace-pre">
                  {block.src}
                </pre>
              </div>
            )
          }
          if (block.t === 'list') {
            return (
              <ul key={i} className="space-y-1 pl-3">
                {block.items.map((item, j) => (
                  <li key={j} className="flex gap-2 text-sm font-mono text-tx-primary">
                    <span className="text-tx-muted flex-shrink-0 mt-px">·</span>
                    <span><InlineText text={item} /></span>
                  </li>
                ))}
              </ul>
            )
          }
          return (
            <p key={i} className="text-sm font-mono text-tx-primary whitespace-pre-wrap break-words leading-relaxed">
              <InlineText text={block.text} />
            </p>
          )
        })}
      </div>
    )
  } catch {
    return <pre className="text-sm font-mono text-tx-primary whitespace-pre-wrap break-words">{content}</pre>
  }
}

// ── PlanPanel ─────────────────────────────────────────────────────────────────
//
// Renders plan[] items returned by the backend.
// Supports FIN items (monto, categoria, ...) and generic key-value.

const PLAN_FIELD_LABELS: Record<string, string> = {
  monto:        'Monto',
  categoria:    'Categoría',
  responsable:  'Responsable',
  fecha:        'Fecha',
  descripcion:  'Descripción',
  moneda:       'Moneda',
  itbms:        'ITBMS',
  metodo_pago:  'Método pago',
  title:        'Título',
  status:       'Estado',
  assignee:     'Asignado',
  priority:     'Prioridad',
  type:         'Tipo',
  // CODE context fields (M27)
  repo_path:    'Repo path',
  base_branch:  'Branch base',
}

/** Per-domain badge color classes */
const DOMAIN_BADGE_COLORS: Record<string, string> = {
  CODE: 'text-accent',
  FIN:  'text-ok',
  WORK: 'text-[#60a5fa]',
}

const SKIP_KEYS = new Set(['id', 'plan_id', 'trace_id'])

// ── GovernanceBadge — Phase 0 ─────────────────────────────────────────────────
//
// Displays MSO governance decision on assistant messages when present.
// Subtle badge that shows decision type and optional reason.

const GOVERNANCE_STYLES: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  ALLOW:                { bg: 'bg-ok/10',   border: 'border-ok/25',   text: 'text-ok',   icon: '✓' },
  BLOCK:                { bg: 'bg-err/10',  border: 'border-err/25',  text: 'text-err',  icon: '✕' },
  REQUIRE_CONFIRMATION: { bg: 'bg-warn/10', border: 'border-warn/25', text: 'text-warn', icon: '⚠' },
  DEGRADED:             { bg: 'bg-warn/10', border: 'border-warn/25', text: 'text-warn', icon: '◐' },
}

function GovernanceBadge({ trace }: { trace: GovernanceTrace }) {
  const style = GOVERNANCE_STYLES[trace.decision] ?? GOVERNANCE_STYLES.ALLOW
  
  // Don't show badge for simple ALLOW decisions without additional context
  if (trace.decision === 'ALLOW' && !trace.reason && !trace.risk_level) {
    return null
  }

  return (
    <div className={`mt-2 pt-2 border-t border-os-border`}>
      <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-mono ${style.bg} ${style.border} border`}>
        <span className={style.text}>{style.icon}</span>
        <span className={style.text}>{trace.decision}</span>
        {trace.risk_level && trace.risk_level !== 'low' && (
          <>
            <span className="text-tx-muted/40">·</span>
            <span className={trace.risk_level === 'critical' ? 'text-err' : trace.risk_level === 'high' ? 'text-warn' : 'text-tx-muted'}>
              {trace.risk_level} risk
            </span>
          </>
        )}
      </div>
      {trace.reason && (
        <p className="text-[10px] font-mono text-tx-muted mt-1 ml-0.5">{trace.reason}</p>
      )}
    </div>
  )
}

function strVal(v: unknown): string | null {
  if (typeof v === 'string' && v.length > 0) return v
  if (typeof v === 'number') return String(v)
  return null
}

// ── buildChatAction ───────────────────────────────────────────────────────────
//
// Converts a ChatUIAction interaction into the structured ChatAction contract.
// The backend (M12+) uses action.type as the primary intent signal — text is
// a backward-compat fallback only.
//
// M23 fixes:
//  • 'confirm' uiAction with choice='cancel' must emit type:'cancel'
//    (previously always emitted 'confirm', so cancel executed instead of cancelling)
//  • 'form' uiAction must emit type:'form_submit' — 'form' is not in
//    STRUCTURED_ACTION_TYPES so it fell through to text routing

function buildChatAction(
  uiAction: ChatUIAction,
  choice: string,
  traceId?: string,
  data?: Record<string, unknown>,
): ChatAction {
  const base = { target: traceId }
  switch (uiAction.type) {
    case 'confirm':
      // FIX M23-B3: use the actual choice as action type — cancel must be 'cancel'
      return { ...base, type: choice === 'cancel' ? 'cancel' : 'confirm', payload: { choice } }
    case 'select':
      return { ...base, type: 'select', payload: { choice } }
    case 'form':
      // FIX M23-B2: backend STRUCTURED_ACTION_TYPES uses 'form_submit', not 'form'
      return { ...base, type: 'form_submit', payload: data ?? {} }
    case 'chip':
    default:
      return { type: 'chip', payload: { text: choice } }
  }
}

interface PlanItemCardProps {
  item: PlanItem
  index: number
  onExecute?: (item: PlanItem, index: number) => void
  disabled?: boolean
}

function PlanItemCard({ item, index, onExecute, disabled }: PlanItemCardProps) {
  // CODE step items: render as numbered step row (no card chrome)
  if (typeof item.step === 'number' && typeof item.description === 'string') {
    return (
      <div className="flex items-start gap-2.5 py-1">
        <span className="text-[11px] font-mono text-accent w-5 flex-shrink-0 pt-0.5">
          {item.step as number}.
        </span>
        <div className="flex-1 min-w-0">
          <span className="text-xs text-tx-primary">{item.description as string}</span>
          {typeof item.action === 'string' && (
            <span className="ml-2 text-[9px] font-mono text-tx-muted/60 uppercase tracking-wider">
              {item.action as string}
            </span>
          )}
        </div>
      </div>
    )
  }

  const entries = Object.entries(item).filter(([k, v]) =>
    !SKIP_KEYS.has(k) && v !== null && v !== undefined && v !== ''
  )
  if (!entries.length) return null
  const categoria = strVal(item.categoria)
  const title     = strVal(item.title)
  return (
    <div className="rounded-lg border border-os-border bg-os-elevated overflow-hidden">
      <div className="px-3 py-1.5 border-b border-os-border bg-os-surface flex items-center gap-1.5">
        <span className="text-[10px] font-mono text-tx-muted">#{index + 1}</span>
        {categoria && (
          <span className="text-[10px] font-mono text-tx-secondary">{categoria}</span>
        )}
        {title && (
          <span className="text-[10px] font-mono text-tx-secondary">{title}</span>
        )}
        {onExecute && (
          <button
            onClick={() => !disabled && onExecute(item, index)}
            disabled={disabled}
            className="
              ml-auto px-2 py-0.5 text-[10px] font-mono rounded border transition-colors
              bg-accent/10 border-accent/25 text-accent
              hover:bg-accent/20
              disabled:opacity-30 disabled:cursor-not-allowed
            "
          >
            Ejecutar
          </button>
        )}
      </div>
      <div className="px-3 py-2 space-y-1">
        {entries.map(([key, val]) => (
          <div key={key} className="flex items-baseline gap-2">
            <span className="text-[10px] font-mono text-tx-muted w-20 flex-shrink-0">
              {PLAN_FIELD_LABELS[key] ?? key}
            </span>
            <span className="text-xs font-mono text-tx-primary break-words">
              {typeof val === 'number'
                ? (key === 'monto' ? val.toFixed(2) : String(val))
                : String(val)
              }
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface PlanPanelProps {
  items: PlanItem[]
  onExecute?: (item: PlanItem, index: number) => void
  disabled?: boolean
}

function PlanPanel({ items, onExecute, disabled }: PlanPanelProps) {
  if (!items.length) return null
  const isCodeSteps = items.length > 0 && typeof items[0].step === 'number'
  return (
    <div className={`mt-2.5 pt-2.5 border-t border-os-border ${isCodeSteps ? 'space-y-0.5' : 'space-y-2'}`}>
      {!isCodeSteps && (
        <p className="text-[9px] font-mono text-tx-muted uppercase tracking-widest mb-1.5">Plan · {items.length} item(s)</p>
      )}
      {items.map((item, i) => (
        <PlanItemCard key={i} item={item} index={i} onExecute={onExecute} disabled={disabled} />
      ))}
    </div>
  )
}

// ── UIActionBar ───────────────────────────────────────────────────────────────
//
// Renders ui_actions from the backend.
// Each action type has its own UI.
// Local "used" state freezes the bar after first interaction.

type ActionCallback = (action: ChatUIAction, choice: string, data?: Record<string, unknown>) => void

interface UIActionBarProps {
  actions: ChatUIAction[]
  onAction: ActionCallback
  disabled: boolean
}

// ── Confirm ─────────────────────────

interface ConfirmActionProps {
  action: ChatUIAction
  onAction: ActionCallback
  outerDisabled: boolean
}

function ConfirmAction({ action, onAction, outerDisabled }: ConfirmActionProps) {
  const [choice, setChoice] = useState<'confirm' | 'cancel' | null>(null)
  const used = choice !== null

  return (
    <div className="flex gap-2 mt-2.5 pt-2.5 border-t border-os-border">
      <button
        onClick={() => { if (used || outerDisabled) return; setChoice('confirm'); onAction(action, 'confirm') }}
        disabled={used || outerDisabled}
        className={`
          px-3 py-1.5 text-xs font-mono rounded border transition-colors
          ${choice === 'confirm'
            ? 'bg-ok/20 border-ok/40 text-ok cursor-default'
            : 'bg-ok/10 border-ok/30 text-ok hover:bg-ok/20 disabled:opacity-40 disabled:cursor-not-allowed'
          }
        `}
      >
        {choice === 'confirm' ? '✓ Confirmado' : action.label || 'Confirmar'}
      </button>
      <button
        onClick={() => { if (used || outerDisabled) return; setChoice('cancel'); onAction(action, 'cancel') }}
        disabled={used || outerDisabled}
        className={`
          px-3 py-1.5 text-xs font-mono rounded border transition-colors
          ${choice === 'cancel'
            ? 'bg-err/20 border-err/40 text-err cursor-default'
            : 'bg-os-elevated border-os-border text-tx-secondary hover:border-os-border-hi disabled:opacity-40 disabled:cursor-not-allowed'
          }
        `}
      >
        {choice === 'cancel' ? '✕ Cancelado' : 'Cancelar'}
      </button>
    </div>
  )
}

// ── Select ───────────────────────────

interface SelectActionProps {
  action: ChatUIAction
  onAction: ActionCallback
  outerDisabled: boolean
}

function SelectAction({ action, onAction, outerDisabled }: SelectActionProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const options = action.options ?? []

  return (
    <div className="mt-2.5 pt-2.5 border-t border-os-border space-y-1.5">
      {action.label && (
        <p className="text-[10px] font-mono text-tx-muted">{action.label}</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt, i) => (
          <button
            key={i}
            onClick={() => {
              if (selected !== null || outerDisabled) return
              setSelected(opt)
              onAction(action, opt)
            }}
            disabled={selected !== null || outerDisabled}
            className={`
              px-2.5 py-1 text-xs font-mono rounded border transition-colors
              ${selected === opt
                ? 'bg-accent/25 border-accent/50 text-accent cursor-default'
                : selected !== null
                  ? 'opacity-30 cursor-default border-os-border text-tx-muted'
                  : 'bg-os-elevated border-os-border text-tx-secondary hover:border-accent/40 hover:text-accent disabled:cursor-not-allowed'
              }
            `}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Form ─────────────────────────────

interface FormActionProps {
  action: ChatUIAction
  onAction: ActionCallback
  outerDisabled: boolean
}

function FormAction({ action, onAction, outerDisabled }: FormActionProps) {
  const fields = action.fields ?? []
  // M27: initialize with backend-provided pre-filled values when available
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(f => [f, action.values?.[f] ?? '']))
  )
  const [submitted, setSubmitted] = useState(false)

  function handleSubmit() {
    if (submitted || outerDisabled) return
    // Send all fields (even empty ones so backend can clear them intentionally)
    const allEntries = Object.entries(values)
    if (!allEntries.length) return
    // Backward-compat text + structured data for M11 ChatAction payload
    const filled = allEntries.filter(([, v]) => v.trim())
    const text = filled.map(([k, v]) => `${k}: ${v.trim()}`).join(', ')
    const data = Object.fromEntries(allEntries.map(([k, v]) => [k, v.trim()]))
    setSubmitted(true)
    onAction(action, text, data)
  }

  if (!fields.length) return null

  return (
    <div className="mt-2.5 pt-2.5 border-t border-os-border space-y-2">
      {action.label && (
        <p className="text-[10px] font-mono text-tx-muted">{action.label}</p>
      )}
      <div className="space-y-1.5">
        {fields.map(field => (
          <div key={field} className="flex items-center gap-2">
            <label className="text-[10px] font-mono text-tx-muted w-24 flex-shrink-0">
              {PLAN_FIELD_LABELS[field] ?? field}
            </label>
            <input
              type={field === 'monto' ? 'number' : 'text'}
              value={values[field]}
              onChange={e => setValues(prev => ({ ...prev, [field]: e.target.value }))}
              disabled={submitted || outerDisabled}
              placeholder={action.values?.[field] ? '' : `${field}…`}
              className="
                flex-1 bg-os-base border border-os-border rounded px-2 py-1
                text-xs font-mono text-tx-primary placeholder:text-tx-muted
                outline-none focus:border-accent/40 transition-colors
                disabled:opacity-50 disabled:cursor-not-allowed
              "
            />
          </div>
        ))}
      </div>
      <button
        onClick={handleSubmit}
        disabled={submitted || outerDisabled}
        className="
          px-3 py-1.5 text-xs font-mono rounded border transition-colors
          bg-accent/10 border-accent/30 text-accent
          hover:bg-accent/20
          disabled:opacity-40 disabled:cursor-not-allowed
        "
      >
        {submitted ? '✓ Enviado' : 'Confirmar'}
      </button>
    </div>
  )
}

// ── Chip bar ─────────────────────────

interface ChipBarProps {
  actions: ChatUIAction[]
  onAction: ActionCallback
  outerDisabled: boolean
}

function ChipBar({ actions, onAction, outerDisabled }: ChipBarProps) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-2.5 pt-2.5 border-t border-os-border">
      {actions.map((action, i) => (
        <button
          key={i}
          onClick={() => !outerDisabled && onAction(action, action.options?.[0] ?? action.label)}
          disabled={outerDisabled}
          className="
            px-2.5 py-1 text-[11px] font-mono rounded border
            bg-accent/10 border-accent/25 text-accent
            hover:bg-accent/20 transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed
          "
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}

// ── UIActionBar (dispatcher) ─────────────────────────────────────────────────

function UIActionBar({ actions, onAction, disabled }: UIActionBarProps) {
  if (!actions.length) return null

  const chips    = actions.filter(a => a.type === 'chip')
  const confirms = actions.filter(a => a.type === 'confirm')
  const selects  = actions.filter(a => a.type === 'select')
  const forms    = actions.filter(a => a.type === 'form')

  return (
    <div>
      {confirms.map((a, i) => (
        <ConfirmAction key={i} action={a} onAction={onAction} outerDisabled={disabled} />
      ))}
      {selects.map((a, i) => (
        <SelectAction key={i} action={a} onAction={onAction} outerDisabled={disabled} />
      ))}
      {forms.map((a, i) => (
        <FormAction key={i} action={a} onAction={onAction} outerDisabled={disabled} />
      ))}
      {chips.length > 0 && (
        <ChipBar actions={chips} onAction={onAction} outerDisabled={disabled} />
      )}
    </div>
  )
}

// ── Message components ────────────────────────────────────────────────────────

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm bg-accent/20 border border-accent/30">
        <p className="text-sm font-mono text-tx-primary whitespace-pre-wrap break-words">{content}</p>
      </div>
    </div>
  )
}

function LoadingMessage() {
  return (
    <div className="flex justify-start items-end gap-2">
      <div className="w-6 h-6 rounded-full bg-os-elevated border border-os-border flex items-center justify-center flex-shrink-0 mb-0.5">
        <span className="text-[9px] font-mono text-tx-muted">AI</span>
      </div>
      <div className="flex items-center gap-1.5 px-3.5 py-3 rounded-2xl rounded-tl-sm bg-os-surface border border-os-border">
        <span className="w-1.5 h-1.5 rounded-full bg-accent/70 animate-pulse" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-accent/70 animate-pulse" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-accent/70 animate-pulse" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}

function ErrorMessage({
  content,
  executionStatus,
  executionStatusSource,
  onRetry,
}: {
  content: string
  executionStatus?: ExecutionStatus
  executionStatusSource?: ExecutionStatusSource
  onRetry?: () => void
}) {
  return (
    <div className="flex justify-start items-start gap-2">
      <div className="w-6 h-6 rounded-full bg-err/15 border border-err/30 flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className="text-[9px] font-mono text-err">!</span>
      </div>
      <div className="max-w-[75%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm bg-err/8 border border-err/25">
        <p className="text-[10px] font-mono text-err/60 uppercase tracking-widest mb-1">Error de conexión</p>
        <p className="text-xs font-mono text-err/90 break-words">{content}</p>
        {executionStatus && (
          <div className="mt-2">
            <ExecutionStatusBadge status={executionStatus} source={executionStatusSource} />
          </div>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-1.5 text-[10px] font-mono text-err/70 hover:text-err underline underline-offset-2 transition-colors"
          >
            Reintentar
          </button>
        )}
      </div>
    </div>
  )
}

interface AssistantMessageProps {
  msg: ChatMessage
  onAction: ActionCallback
  onPlanExecute: (msgId: string, item: PlanItem, index: number) => void
  isSending: boolean
}

function AssistantMessage({ msg, onAction, onPlanExecute, isSending }: AssistantMessageProps) {
  const isConfirmationRequest = msg.kind === 'confirmation_request'
  // Freeze all interactive elements once this message has been acted upon
  const isHandled = msg.handled === true
  const isDisabled = isSending || isHandled

  return (
    <div className="flex justify-start items-start gap-2">
      <div className="w-6 h-6 rounded-full bg-os-elevated border border-os-border flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className="text-[9px] font-mono text-tx-muted">AI</span>
      </div>
      <div className={`
        max-w-[78%] px-3.5 py-2.5 rounded-2xl rounded-tl-sm
        ${isConfirmationRequest
          ? 'bg-warn/8 border border-warn/30'
          : 'bg-os-surface border border-os-border'
        }
      `}>
        {msg.meta?.domain && (
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className={`text-[9px] font-mono uppercase tracking-widest ${DOMAIN_BADGE_COLORS[msg.meta.domain] ?? 'text-tx-muted'}`}>
              {msg.meta.domain}
            </span>
            {msg.meta.intent && msg.meta.intent !== 'unknown' && (
              <>
                <span className="text-tx-muted/40 text-[9px]">·</span>
                <span className="text-[9px] font-mono text-tx-muted/70">{msg.meta.intent}</span>
              </>
            )}
          </div>
        )}

        <RichText content={msg.content} />

        {msg.executionStatus && (
          <div className="mt-2">
            <ExecutionStatusBadge status={msg.executionStatus} source={msg.executionStatusSource} />
          </div>
        )}

        {msg.plan && msg.plan.length > 0 && (
          <PlanPanel
            items={msg.plan}
            onExecute={(item, index) => onPlanExecute(msg.id, item, index)}
            disabled={isDisabled}
          />
        )}

        {msg.uiActions && msg.uiActions.length > 0 && (
          <UIActionBar
            actions={msg.uiActions}
            onAction={onAction}
            disabled={isDisabled}
          />
        )}

        {/* Phase 0: Governance decision visibility */}
        {msg.governanceTrace && (
          <GovernanceBadge trace={msg.governanceTrace} />
        )}
      </div>
    </div>
  )
}

function SystemMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-center my-1">
      <div className="px-3 py-1.5 rounded-full bg-os-elevated border border-os-border">
        <p className="text-[10px] font-mono text-tx-muted text-center">{content}</p>
      </div>
    </div>
  )
}

// ── ChatThread ────────────────────────────────────────────────────────────────

type MsgActionHandler = (msgId: string, action: ChatUIAction, choice: string, data?: Record<string, unknown>) => void

interface ChatThreadProps {
  messages:           ChatMessage[]
  onAction:           MsgActionHandler
  onPlanExecute:      (msgId: string, item: PlanItem, index: number) => void
  isSending:          boolean
  /** Incremented by ChatView when user sends — forces scroll to bottom. */
  scrollToBottomTick: number
  /** Called with the error message id when the user clicks "Reintentar". */
  onRetry:            (msgId: string) => void
  /** M21: message id to scroll into view after session load. */
  scrollToMessageId?: string | null
  /** M22: called once the target message has been scrolled to (or timed out). */
  onScrollComplete?: () => void
}

function ChatThread({
  messages, onAction, onPlanExecute, isSending,
  scrollToBottomTick, onRetry, scrollToMessageId, onScrollComplete,
}: ChatThreadProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Force-scroll when user dispatches a message
  useEffect(() => {
    if (scrollToBottomTick > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [scrollToBottomTick])

  // Conditional scroll when messages update (response arrives, history loads)
  // Only fires if the user is already near the bottom to avoid disrupting reading
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    if (distFromBottom < 150) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  // M22: scroll to a specific message after deep-search navigation.
  // Retries at 150 ms, 500 ms, and 1 200 ms to handle the case where the
  // session detail (and its messages) haven't rendered yet on the first attempt.
  useEffect(() => {
    if (!scrollToMessageId) return
    let cancelled = false

    const tryScroll = (): boolean => {
      const el = document.querySelector(`[data-message-id="${scrollToMessageId}"]`)
      if (!el) return false
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      if (!cancelled) onScrollComplete?.()
      return true
    }

    if (tryScroll()) return

    const t1 = setTimeout(() => { if (!cancelled) tryScroll() }, 150)
    const t2 = setTimeout(() => { if (!cancelled) tryScroll() }, 500)
    // Final attempt: call onScrollComplete regardless so the state is cleared
    const t3 = setTimeout(() => {
      if (!cancelled) { tryScroll(); onScrollComplete?.() }
    }, 1200)

    return () => { cancelled = true; clearTimeout(t1); clearTimeout(t2); clearTimeout(t3) }
  }, [scrollToMessageId, messages, onScrollComplete])

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto flex items-center justify-center px-6 py-8">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center mx-auto">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" className="text-accent">
              <path d="M3 4a1 1 0 011-1h12a1 1 0 011 1v9a1 1 0 01-1 1H11l-4 3v-3H4a1 1 0 01-1-1V4z"
                stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-mono text-tx-secondary">AssistantOS</p>
            <p className="text-xs font-mono text-tx-muted mt-1">Escribe un mensaje para empezar</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map(msg => {
        const msgAttrs = { 'data-message-id': msg.id }
        if (msg.role === 'system') return (
          <div key={msg.id} {...msgAttrs}><SystemMessage content={msg.content} /></div>
        )
        if (msg.role === 'user') return (
          <div key={msg.id} {...msgAttrs}><UserMessage content={msg.content} /></div>
        )
        if (msg.status === 'loading') return (
          <div key={msg.id} {...msgAttrs}><LoadingMessage /></div>
        )
        if (msg.status === 'error') return (
          <div key={msg.id} {...msgAttrs}>
            <ErrorMessage
              content={msg.content}
              executionStatus={msg.executionStatus}
              executionStatusSource={msg.executionStatusSource}
              onRetry={() => onRetry(msg.id)}
            />
          </div>
        )
        return (
          <div key={msg.id} {...msgAttrs}>
            <AssistantMessage
              msg={msg}
              onAction={(uiAction, choice, data) => onAction(msg.id, uiAction, choice, data)}
              onPlanExecute={onPlanExecute}
              isSending={isSending}
            />
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

// ── ChatComposer ──────────────────────────────────────────────────────────────

interface ComposerProps {
  onSend: (text: string) => void
  disabled: boolean
}

function ChatComposer({ onSend, disabled }: ComposerProps) {
  const [draft, setDraft] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canSend = draft.trim().length > 0 && !disabled

  function autoResize() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  function handleSubmit() {
    const text = draft.trim()
    if (!text || disabled) return
    onSend(text)
    setDraft('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    textareaRef.current?.focus()
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="px-4 py-3 border-t border-os-border bg-os-base flex-shrink-0">
      <div className="flex items-end gap-2 px-3.5 py-2 bg-os-surface border border-os-border rounded-xl focus-within:border-accent/40 transition-colors">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={e => { setDraft(e.target.value); autoResize() }}
          onKeyDown={handleKeyDown}
          placeholder="Escribe un mensaje… (Enter envía, Shift+Enter = newline)"
          rows={1}
          disabled={disabled}
          className="
            flex-1 bg-transparent text-sm font-mono text-tx-primary
            placeholder:text-tx-muted resize-none outline-none
            disabled:cursor-not-allowed disabled:opacity-50
            py-0.5 leading-relaxed
          "
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSend}
          aria-label="Enviar"
          className="
            flex-shrink-0 w-8 h-8 rounded-lg
            bg-accent/15 border border-accent/30 text-accent
            flex items-center justify-center
            hover:bg-accent/25 transition-colors
            disabled:opacity-30 disabled:cursor-not-allowed
          "
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 7h10M7 2l5 5-5 5" stroke="currentColor" strokeWidth="1.4"
              strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// ── Pin persistence helpers ───────────────────────────────────────────────────

const PINS_KEY = 'assistantos.chat.pins.v1'

function loadPins(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(PINS_KEY) ?? '{}') as Record<string, boolean> }
  catch { return {} }
}
function savePins(pins: Record<string, boolean>): void {
  try { localStorage.setItem(PINS_KEY, JSON.stringify(pins)) }
  catch {}
}

// ── SessionSidebar — M20 ──────────────────────────────────────────────────────
//
// Features:
//   • Search box (⌘K to focus) — filters by title in real time
//   • Pinned sessions float to top (persisted in localStorage)
//   • Inline rename — click pencil icon on hover
//   • Keyboard navigation — ↑/↓ in search, Enter to activate
//   • Delete button on hover (hidden if only one session)

// ── highlightMatch ────────────────────────────────────────────────────────────
// Returns spans with the matching substring highlighted.

function highlightMatch(text: string, query: string): ReactNode {
  if (!query) return text
  const idx = text.toLowerCase().indexOf(query.toLowerCase())
  if (idx === -1) return text
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-accent/30 text-tx-primary rounded-sm">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  )
}

function SessionSidebar({
  sessions,
  activeSessionId,
  loading,
  error,
  onNew,
  onSelect,
  onDelete,
  onRename,
  onRetryLoad,
  onNavigate,
}: {
  sessions:        ChatSession[]
  activeSessionId: string | null
  loading:         boolean
  error:           string | null
  onNew:           () => void
  onSelect:        (id: string) => void
  onDelete:        (id: string) => void
  onRename:        (id: string, title: string) => void
  onRetryLoad:     () => void
  onNavigate:      (sessionId: string, messageId: string) => void
}) {
  const [query,       setQuery]       = useState('')
  const [pins,        setPins]        = useState<Record<string, boolean>>(() => loadPins())
  const [editingId,   setEditingId]   = useState<string | null>(null)
  const [editValue,   setEditValue]   = useState('')
  const [focusedIdx,  setFocusedIdx]  = useState(-1)
  const [deepResults,    setDeepResults]    = useState<MessageSearchResult[]>([])
  const [deepLoading,    setDeepLoading]    = useState(false)
  const [deepFocusedIdx, setDeepFocusedIdx] = useState(-1)
  const searchRef = useRef<HTMLInputElement>(null)

  // M21: debounced deep search when query.length >= 2
  useEffect(() => {
    if (query.length < 2) { setDeepResults([]); setDeepLoading(false); return }
    setDeepLoading(true)
    const t = setTimeout(async () => {
      const results = await apiSearchMessages(query)
      setDeepResults(results)
      setDeepLoading(false)
    }, 200)
    return () => { clearTimeout(t); setDeepLoading(false) }
  }, [query])

  // Reset keyboard focus when query or session list changes
  useEffect(() => { setFocusedIdx(-1) }, [query, sessions.length])
  // Reset deep keyboard focus when results change
  useEffect(() => { setDeepFocusedIdx(-1) }, [deepResults])

  // ⌘K / Ctrl+K → focus search
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  // ── Derived data ─────────────────────────────────────────────────────────

  const filtered = sessions.filter(s =>
    !query.trim() || s.title.toLowerCase().includes(query.toLowerCase()),
  )
  const byUpdated = (a: ChatSession, b: ChatSession) =>
    new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  const sorted = [
    ...filtered.filter(s =>  pins[s.id]).sort(byUpdated),
    ...filtered.filter(s => !pins[s.id]).sort(byUpdated),
  ]

  // ── Handlers ─────────────────────────────────────────────────────────────

  function togglePin(id: string) {
    const next = { ...pins }
    if (next[id]) delete next[id]
    else next[id] = true
    setPins(next)
    savePins(next)
  }

  function startRename(id: string, title: string) {
    setEditingId(id)
    setEditValue(title)
  }

  function confirmRename() {
    if (!editingId) return
    const val = editValue.trim()
    if (val) onRename(editingId, val)
    setEditingId(null)
  }

  function handleSearchKey(e: KeyboardEvent<HTMLInputElement>) {
    const isDeep = query.length >= 2
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        if (isDeep) setDeepFocusedIdx(i => Math.min(i + 1, deepResults.length - 1))
        else        setFocusedIdx(i => Math.min(i + 1, sorted.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        if (isDeep) setDeepFocusedIdx(i => Math.max(i - 1, -1))
        else        setFocusedIdx(i => Math.max(i - 1, -1))
        break
      case 'Enter': {
        e.preventDefault()
        if (isDeep) {
          const result = deepResults[deepFocusedIdx]
          if (result) { onNavigate(result.sessionId, result.messageId); setQuery('') }
        } else {
          const sess = sorted[focusedIdx]
          if (sess) { onSelect(sess.id); setQuery(''); searchRef.current?.blur() }
        }
        break
      }
      case 'Escape':
        setQuery('')
        setFocusedIdx(-1)
        setDeepFocusedIdx(-1)
        searchRef.current?.blur()
        break
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="w-48 border-r border-os-border flex flex-col flex-shrink-0 overflow-hidden">

      {/* Header: new chat + search */}
      <div className="px-3 pt-2.5 pb-2 border-b border-os-border space-y-2">
        <button
          onClick={onNew}
          disabled={loading}
          className="w-full text-left text-[11px] font-mono text-tx-secondary hover:text-tx-primary transition-colors flex items-center gap-1.5 disabled:opacity-50"
        >
          <span className="text-accent">+</span> Nuevo chat
        </button>

        <div className="relative">
          <input
            ref={searchRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleSearchKey}
            placeholder="Buscar…  ⌘K"
            className="
              w-full bg-os-surface border border-os-border rounded px-2 py-[3px] pr-5
              text-[10px] font-mono text-tx-primary placeholder:text-tx-muted/60
              outline-none focus:border-accent/40 transition-colors
            "
          />
          {query && (
            <button
              tabIndex={-1}
              onClick={() => { setQuery(''); searchRef.current?.focus() }}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-tx-muted hover:text-tx-primary text-[12px] leading-none"
              aria-label="Limpiar"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Session list or deep-search results */}
      <div className="flex-1 overflow-y-auto py-1">

        {loading && sessions.length === 0 && (
          <p className="px-3 py-2 text-[10px] font-mono text-tx-muted animate-pulse">cargando…</p>
        )}

        {error && !loading && (
          <div className="px-3 py-2 space-y-1">
            <p className="text-[10px] font-mono text-err/80 leading-tight">Error al cargar</p>
            <button
              onClick={onRetryLoad}
              className="text-[10px] font-mono text-accent hover:text-tx-primary underline underline-offset-2"
            >
              Reintentar
            </button>
          </div>
        )}

        {/* M22: deep message search results when query >= 2 chars */}
        {query.length >= 2 && (
          <div>
            {/* Skeleton loading */}
            {deepLoading && (
              <div className="px-3 py-2 space-y-2.5">
                {[0, 1, 2].map(i => (
                  <div key={i} className="space-y-1 animate-pulse">
                    <div className="h-1.5 bg-os-elevated rounded w-2/3" />
                    <div className="h-2.5 bg-os-elevated rounded w-full" />
                    <div className="h-2.5 bg-os-elevated rounded w-4/5" />
                  </div>
                ))}
              </div>
            )}

            {/* Empty state */}
            {!deepLoading && deepResults.length === 0 && (
              <div className="px-3 py-5 flex flex-col items-center gap-2 text-center">
                <svg width="18" height="18" viewBox="0 0 20 20" fill="none" className="text-tx-muted/40 flex-shrink-0">
                  <circle cx="9" cy="9" r="5.5" stroke="currentColor" strokeWidth="1.3"/>
                  <path d="M13.5 13.5L17 17" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                  <path d="M6.5 9h5M9 6.5v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity=".4"/>
                </svg>
                <div>
                  <p className="text-[10px] font-mono text-tx-muted">Sin resultados para</p>
                  <p className="text-[10px] font-mono text-tx-secondary mt-0.5 break-all">«{query}»</p>
                </div>
              </div>
            )}

            {/* Result count */}
            {!deepLoading && deepResults.length > 0 && (
              <p className="px-3 py-1 text-[9px] font-mono text-tx-muted border-b border-os-border/40">
                {deepResults.length} resultado{deepResults.length !== 1 ? 's' : ''} · ↑↓ navegar
              </p>
            )}

            {/* Result items */}
            {!deepLoading && deepResults.map((r, idx) => (
              <button
                key={r.messageId}
                onClick={() => { onNavigate(r.sessionId, r.messageId); setQuery('') }}
                className={`w-full text-left px-3 py-2 transition-colors border-b border-os-border/30 last:border-0 ${
                  deepFocusedIdx === idx
                    ? 'bg-os-elevated'
                    : 'hover:bg-os-elevated/60'
                }`}
              >
                <p className="text-[9px] font-mono text-accent/80 truncate">
                  {highlightMatch(r.sessionTitle, query)}
                </p>
                <p className="text-[10px] font-mono text-tx-secondary leading-snug mt-0.5 line-clamp-2 break-words">
                  {highlightMatch(r.text, query)}
                </p>
              </button>
            ))}
          </div>
        )}

        {/* Normal session list when query < 2 chars */}
        {query.length < 2 && !loading && !error && sessions.length === 0 && (
          <p className="px-3 py-2 text-[10px] font-mono text-tx-muted">Sin sesiones</p>
        )}

        {query.length < 2 && sorted.map((sess, idx) => {
          const isActive  = sess.id === activeSessionId
          const isPinned  = Boolean(pins[sess.id])
          const isFocused = focusedIdx === idx
          const isEditing = editingId  === sess.id

          return (
            <div
              key={sess.id}
              className={`group flex items-center px-2 py-1.5 cursor-pointer transition-colors gap-1 min-w-0 ${
                isActive
                  ? 'bg-os-elevated text-tx-primary'
                  : isFocused
                    ? 'bg-os-elevated/50 text-tx-secondary'
                    : 'text-tx-muted hover:bg-os-elevated hover:text-tx-secondary'
              }`}
              onClick={() => { if (!isEditing) onSelect(sess.id) }}
            >
              {/* Pin dot */}
              {isPinned && (
                <span className="text-[8px] text-accent/80 flex-shrink-0 leading-none">◆</span>
              )}

              {/* Title or rename input */}
              {isEditing ? (
                <input
                  autoFocus
                  value={editValue}
                  onChange={e => setEditValue(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter')  { e.preventDefault(); confirmRename() }
                    if (e.key === 'Escape') { setEditingId(null) }
                  }}
                  onBlur={confirmRename}
                  onClick={e => e.stopPropagation()}
                  className="flex-1 min-w-0 bg-transparent text-[10px] font-mono text-tx-primary outline-none border-b border-accent/50"
                />
              ) : (
                <span className="flex-1 min-w-0 text-[10px] font-mono truncate">
                  {sess.title}
                </span>
              )}

              {/* Action buttons — visible on hover */}
              {!isEditing && (
                <div className="opacity-0 group-hover:opacity-100 flex items-center flex-shrink-0 transition-opacity">
                  {/* Rename */}
                  <button
                    onClick={e => { e.stopPropagation(); startRename(sess.id, sess.title) }}
                    className="w-4 h-4 flex items-center justify-center text-tx-muted hover:text-accent transition-colors"
                    aria-label="Renombrar"
                    title="Renombrar"
                  >
                    <svg width="8" height="8" viewBox="0 0 12 12" fill="none">
                      <path d="M8.5 1.5l2 2-7 7H1.5v-2l7-7z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
                    </svg>
                  </button>
                  {/* Pin toggle */}
                  <button
                    onClick={e => { e.stopPropagation(); togglePin(sess.id) }}
                    className={`w-4 h-4 flex items-center justify-center text-[9px] leading-none transition-colors ${
                      isPinned ? 'text-accent' : 'text-tx-muted hover:text-accent'
                    }`}
                    aria-label={isPinned ? 'Quitar pin' : 'Fijar'}
                    title={isPinned ? 'Quitar pin' : 'Fijar arriba'}
                  >
                    {isPinned ? '◆' : '◇'}
                  </button>
                  {/* Delete */}
                  {sessions.length > 1 && (
                    <button
                      onClick={e => { e.stopPropagation(); onDelete(sess.id) }}
                      className="w-4 h-4 flex items-center justify-center text-tx-muted hover:text-err transition-colors text-[12px] leading-none"
                      aria-label="Eliminar"
                      title="Eliminar sesión"
                    >
                      ×
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ── ChatView ──────────────────────────────────────────���───────────────────────

/** Params stored for retry when a send fails. */
type FailedDispatch = {
  loadingId: string
  userMsgId: string
  params: { text?: string; action?: ChatAction; sourceMsgId?: string; displayText?: string }
}

export function ChatView() {
  const [messages,         setMessages]         = useState<ChatMessage[]>([])
  const [isSending,        setIsSending]        = useState(false)
  // Incremented each time the user sends — triggers force-scroll in ChatThread
  const [sendTick,         setSendTick]         = useState(0)
  // M21: message id to scroll into view after deep-search navigation
  const [scrollToMessageId, setScrollToMessageId] = useState<string | null>(null)
  // M23 FIX: store full session context (not just context_id).
  // pending_flow + pending_data must round-trip to the backend so confirm/cancel/
  // select/form_submit resolve the active flow instead of returning passthrough.
  const sessionContextRef  = useRef<{
    context_id?:   string
    pending_flow?: string | null
    pending_data?: Record<string, unknown>
    last_domain?:  string | null
  }>({})
  // Ref copy of activeSessionId for use in stable callbacks without changing deps
  const activeSessionIdRef = useRef<string | null>(null)
  // Stores params of the last failed send, keyed by loadingId, for retry
  const lastFailedRef      = useRef<FailedDispatch | null>(null)

  const {
    sessions, sessionDetails, activeSessionId,
    loading, detailLoadingId, sessionsError, detailError,
    fetchSessions, loadSessionDetail, createSessionRemote, renameSessionRemote, deleteSessionRemote,
  } = useChatSessionsStore()

  const webhookStatus = useUIStore(s => s.systemData.webhookStatus)

  // ── M18: Initialise sessions from backend once on mount ───────────────────
  useEffect(() => { fetchSessions() }, [fetchSessions])

  // ── M18: Sync activeSessionIdRef (used inside stable callbacks) ───────────
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId ?? null
  }, [activeSessionId])

  // ── M18/M23: Load messages + seed session context when session changes
  // Reset sessionContextRef to only the persisted context_id when switching sessions.
  // This clears any stale pending_flow from the previous session so it cannot
  // contaminate a new turn in a different session.
  useEffect(() => {
    const detail = activeSessionId ? sessionDetails[activeSessionId] : undefined
    setMessages((detail?.messages as ChatMessage[]) ?? [])
    sessionContextRef.current = detail?.contextId
      ? { context_id: detail.contextId }
      : {}
  }, [activeSessionId, sessionDetails]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── coreDispatch ─────────────────────────────────────────────────────────
  // Central send primitive. Adds user bubble + loading bubble, calls API,
  // replaces loading with response. Marks sourceMsgId as handled if provided.
  //
  // Race guard: snapshots requestSessionId at start; discards responses that
  // arrive after the user has switched to a different session.
  const coreDispatch = useCallback(async (params: {
    text?: string
    action?: ChatAction
    sourceMsgId?: string
    displayText?: string
  }) => {
    if (isSending) return
    const { text, action, sourceMsgId, displayText } = params

    // Snapshot session at call time — used for race guard and session_id
    const requestSessionId = activeSessionIdRef.current
    const userContent      = displayText ?? text ?? `[${action?.type ?? 'action'}]`

    const userMsgId = genId()
    const userMsg: ChatMessage = {
      id: userMsgId, role: 'user', content: userContent,
      status: 'sent', createdAt: new Date().toISOString(),
    }
    const loadingId = genId()
    const loadingMsg: ChatMessage = {
      id: loadingId, role: 'assistant', content: '',
      status: 'loading', createdAt: new Date().toISOString(),
    }

    // Auto-title: assign first message text as session title
    if (requestSessionId && text) {
      const { sessions: ss, sessionDetails: sd } = useChatSessionsStore.getState()
      const currSess   = ss.find(s => s.id === requestSessionId)
      const currDetail = sd[requestSessionId]
      const isFirst    = !currDetail || currDetail.messages.length === 0
      if (currSess && isFirst && currSess.title === 'Nuevo chat') {
        renameSessionRemote(requestSessionId, text)
      }
    }

    setMessages(prev => {
      // Mark source message handled first, then append user + loading
      const next = sourceMsgId
        ? prev.map(m => m.id === sourceMsgId ? { ...m, handled: true } : m)
        : prev
      return [...next, userMsg, loadingMsg]
    })
    setSendTick(t => t + 1)   // triggers force-scroll in ChatThread
    setIsSending(true)

    // M23 diagnostic: log what action is being dispatched
    if (action) {
      console.debug('[M23][coreDispatch] action:', JSON.stringify(action),
        '| pending_flow:', sessionContextRef.current.pending_flow ?? 'none')
    }

    try {
      const res = await sendChatMessage({
        text,
        action,
        conversation_id: 'ui_chat',
        // M23 FIX: forward the full session context (pending_flow + pending_data)
        // so confirm/cancel/select/form_submit can resolve their pending flow.
        session_context: Object.keys(sessionContextRef.current).length > 0
          ? sessionContextRef.current as SendChatRequest['session_context']
          : undefined,
        session_id: requestSessionId ?? undefined,
      })

      // ── Race guard: if session changed while waiting, discard ──────────────
      if (activeSessionIdRef.current !== requestSessionId) return

      // M23 FIX: save the full session response (pending_flow, pending_data,
      // context_id, last_domain) so the next request can resolve multi-turn flows.
      if (res.session) {
        const s = res.session
        sessionContextRef.current = {
          ...(s.context_id  != null ? { context_id:   s.context_id  }                              : {}),
          ...('pending_flow' in s   ? { pending_flow: s.pending_flow as string | null }             : {}),
          ...('pending_data' in s && s.pending_data != null
                                    ? { pending_data: s.pending_data as Record<string, unknown> }   : {}),
          ...('last_domain'  in s   ? { last_domain:  s.last_domain  as string | null }             : {}),
        }
        console.debug('[M23][coreDispatch] saved session context:',
          JSON.stringify({ context_id: sessionContextRef.current.context_id,
                           pending_flow: sessionContextRef.current.pending_flow }))
      }

      const uiActions = Array.isArray(res.ui_actions) ? res.ui_actions : []
      const plan      = Array.isArray(res.plan) && res.plan.length > 0
        ? (res.plan as PlanItem[])
        : undefined

      const assistantMsg: ChatMessage = {
        id:        loadingId,
        role:      'assistant',
        content:   res.message ?? '(sin respuesta)',
        status:    'sent',
        createdAt: new Date().toISOString(),
        uiActions: uiActions.length > 0 ? uiActions : undefined,
        plan,
        meta: {
          domain:            res.domain,
          intent:            res.intent,
          mode:              res.mode,
          traceId:           res.trace_id,
          needsConfirmation: res.needs_confirmation,
        },
        kind: res.needs_confirmation ? 'confirmation_request' : 'normal',
        // Phase 0: governance trace visibility
        governanceTrace: res.governance_trace,
        executionStatus: res.execution_status,
        executionStatusSource: res.execution_status_source,
      }

      setMessages(prev => prev.map(m => m.id === loadingId ? assistantMsg : m))
      lastFailedRef.current = null

    } catch (err) {
      // Store params so the user can retry with the same message
      lastFailedRef.current = { loadingId, userMsgId, params }
      const errMsg = err instanceof Error ? err.message : String(err)
      const executionStatus = err instanceof ChatApiError ? err.executionStatus : 'unavailable'
      const executionStatusSource = err instanceof ChatApiError ? err.executionStatusSource : 'ui_fallback'
      setMessages(prev => prev.map(m =>
        m.id === loadingId ? { ...m, status: 'error', content: errMsg, executionStatus, executionStatusSource } : m,
      ))
    } finally {
      setIsSending(false)
    }
  }, [isSending, renameSessionRemote])

  // ── handleRetry ───────────────────────────────────────────────────────────
  // Removes the error bubble (and its user message), then re-dispatches.
  const handleRetry = useCallback((errorMsgId: string) => {
    const failed = lastFailedRef.current
    if (!failed || failed.loadingId !== errorMsgId) return
    const { userMsgId, params } = failed
    lastFailedRef.current = null
    setMessages(prev => prev.filter(m => m.id !== errorMsgId && m.id !== userMsgId))
    void coreDispatch(params)
  }, [coreDispatch])

  // Plain text send — used by the composer
  const handleSend = useCallback((text: string) => {
    void coreDispatch({ text, displayText: text })
  }, [coreDispatch])

  // Action dispatcher — builds structured ChatAction + backward-compat text,
  // then delegates to coreDispatch which marks the source message as handled.
  const handleAction = useCallback((
    msgId: string,
    uiAction: ChatUIAction,
    choice: string,
    data?: Record<string, unknown>,
  ) => {
    // Retrieve traceId from the source message for action targeting
    const traceId = messages.find(m => m.id === msgId)?.meta?.traceId
    const action  = buildChatAction(uiAction, choice, traceId, data)

    let text: string
    switch (uiAction.type) {
      case 'confirm':
        text = choice === 'confirm' ? 'confirmar' : 'cancelar'
        break
      case 'select':
        text = choice
        break
      case 'form':
        // choice is the human-readable "campo: valor" string from FormAction
        text = choice
        break
      case 'chip':
      default:
        text = choice
        break
    }

    void coreDispatch({ text, action, sourceMsgId: msgId, displayText: text })
  }, [coreDispatch, messages])

  // Plan item execute — dispatches a plan_item_execute structured action
  const handlePlanExecute = useCallback((
    msgId: string,
    item: PlanItem,
    index: number,
  ) => {
    const traceId  = messages.find(m => m.id === msgId)?.meta?.traceId
    const itemTitle = strVal(item.title) ?? strVal(item.categoria) ?? `item ${index + 1}`
    const action: ChatAction = {
      type:    'plan_item_execute',
      target:  traceId,
      id:      String(index),
      payload: item as Record<string, unknown>,
    }
    void coreDispatch({
      text:        `ejecutar ${itemTitle}`,
      action,
      sourceMsgId: msgId,
      displayText: `ejecutar ${itemTitle}`,
    })
  }, [coreDispatch, messages])

  // M21/M22: navigate to a specific message from deep-search
  const handleNavigateToMessage = useCallback((sessionId: string, messageId: string) => {
    setScrollToMessageId(messageId)
    loadSessionDetail(sessionId)
  }, [loadSessionDetail])

  // M22: called by ChatThread once the target message has been scrolled to
  const handleScrollComplete = useCallback(() => setScrollToMessageId(null), [])

  const dotColor =
    webhookStatus === 'ok'      ? 'bg-ok' :
    webhookStatus === 'down'    ? 'bg-err' :
    webhookStatus === 'unknown' ? 'bg-idle' : 'bg-warn'

  const isDetailLoading = detailLoadingId === activeSessionId

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sessions sidebar — M20/M21 */}
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        loading={loading}
        error={sessionsError}
        onNew={() => createSessionRemote()}
        onSelect={id => loadSessionDetail(id)}
        onDelete={id => deleteSessionRemote(id)}
        onRename={(id, title) => renameSessionRemote(id, title)}
        onRetryLoad={fetchSessions}
        onNavigate={handleNavigateToMessage}
      />

      {/* Chat panel */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <div className="px-5 py-3 border-b border-os-border flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor}`} />
            <p className="text-xs font-mono text-tx-secondary">assistant · /chat/process</p>
          </div>
          {isDetailLoading && (
            <span className="text-[10px] font-mono text-tx-muted animate-pulse">cargando…</span>
          )}
        </div>

        {/* Session detail error */}
        {detailError && !isDetailLoading && (
          <div className="px-5 py-2 border-b border-err/20 bg-err/5 flex-shrink-0 flex items-center gap-3">
            <p className="text-[10px] font-mono text-err/80 flex-1">
              Error al cargar sesión — {detailError}
            </p>
            {activeSessionId && (
              <button
                onClick={() => loadSessionDetail(activeSessionId)}
                className="text-[10px] font-mono text-accent hover:text-tx-primary underline underline-offset-2 transition-colors flex-shrink-0"
              >
                Reintentar
              </button>
            )}
          </div>
        )}

        {/* Thread */}
        <ChatThread
          messages={messages}
          onAction={handleAction}
          onPlanExecute={handlePlanExecute}
          isSending={isSending}
          scrollToBottomTick={sendTick}
          onRetry={handleRetry}
          scrollToMessageId={scrollToMessageId}
          onScrollComplete={handleScrollComplete}
        />

        {/* Composer */}
        <ChatComposer onSend={handleSend} disabled={isSending} />
      </div>
    </div>
  )
}
