'use client'

import { useState } from 'react'
import { useUIStore } from '@/stores/ui-store'
import { executeCode } from '@/lib/api'
import type { ExecutionListItem } from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────────────

function genRequestId(): string {
  return `ui_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// ── CODE Run form ─────────────────────────────────────────────────────────────

type FormPhase = 'idle' | 'submitting' | 'success' | 'error'

function CodeRunForm() {
  const { setView, setSelectedExecution, setPendingExecution } = useUIStore()

  const [repoPath,        setRepoPath]        = useState('')
  const [changesRaw,      setChangesRaw]      = useState('')
  const [runTests,        setRunTests]        = useState(false)
  const [allowNeedsReview, setAllowNeedsReview] = useState(true)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [phase,           setPhase]           = useState<FormPhase>('idle')
  const [submitError,     setSubmitError]     = useState<string | null>(null)
  const [lastExecId,      setLastExecId]      = useState<string | null>(null)

  const busy = phase === 'submitting'

  function validate(): boolean {
    if (!repoPath.trim()) {
      setValidationError('repo_path is required.')
      return false
    }
    if (changesRaw.trim()) {
      try {
        const parsed = JSON.parse(changesRaw.trim())
        if (!Array.isArray(parsed)) {
          setValidationError('changes must be a JSON array.')
          return false
        }
      } catch {
        setValidationError('changes contains invalid JSON.')
        return false
      }
    }
    setValidationError(null)
    return true
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (!validate()) return

    const changes = changesRaw.trim() ? JSON.parse(changesRaw.trim()) : []

    const payload = {
      request_id: genRequestId(),
      source:     'ui',
      mode:       'code_execution',
      repo_path:  repoPath.trim(),
      changes,
      test_spec: runTests
        ? { command: ['python', '-m', 'pytest', '-q'], timeout_sec: 60 }
        : null,
      validation_spec: {
        require_tests:      runTests,
        require_changes:    false,
        allow_needs_review: allowNeedsReview,
      },
      metadata: {
        trigger_type:  'ui',
        requested_by:  'local_user',
      },
    }

    setPhase('submitting')
    setSubmitError(null)

    try {
      const result = await executeCode(payload)

      // Build list item for immediate display in Executions
      const newItem: ExecutionListItem = {
        execution_id:     result.execution_id,
        final_status:     result.final_status,
        summary:          result.summary,
        timestamp:        new Date().toISOString(),
        report_json_path: result.report_json_path,
        report_md_path:   result.report_md_path,
        done_path:        result.done_path,
        metadata_path:    null,
        source:           'ui',
      }

      // Share with Executions view via store
      setPendingExecution(newItem)
      setSelectedExecution(result.execution_id)

      setLastExecId(result.execution_id)
      setPhase('success')

      // Navigate to Executions after a short beat so user sees the success state
      setTimeout(() => {
        setView('executions')
      }, 800)

    } catch (err) {
      setPhase('error')
      setSubmitError(String(err))
    }
  }

  function handleReset() {
    setRepoPath('')
    setChangesRaw('')
    setRunTests(false)
    setAllowNeedsReview(true)
    setValidationError(null)
    setSubmitError(null)
    setPhase('idle')
    setLastExecId(null)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* repo_path */}
      <div>
        <label className="block text-[10px] font-mono font-medium text-tx-muted uppercase tracking-wider mb-1.5">
          repo_path <span className="text-err">*</span>
        </label>
        <input
          type="text"
          value={repoPath}
          onChange={e => { setRepoPath(e.target.value); setValidationError(null) }}
          placeholder="/absolute/path/to/repo"
          disabled={busy || phase === 'success'}
          className="
            w-full bg-os-elevated border border-os-border rounded
            px-3 py-2 text-xs font-mono text-tx-primary
            placeholder:text-tx-muted outline-none
            focus:border-accent/50 transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed
          "
        />
      </div>

      {/* changes */}
      <div>
        <label className="block text-[10px] font-mono font-medium text-tx-muted uppercase tracking-wider mb-1.5">
          changes <span className="text-tx-muted font-normal">(JSON array, optional)</span>
        </label>
        <textarea
          value={changesRaw}
          onChange={e => { setChangesRaw(e.target.value); setValidationError(null) }}
          placeholder={'[\n  {"type": "edit", "path": "src/file.py", "content": "..."}\n]'}
          rows={5}
          disabled={busy || phase === 'success'}
          className="
            w-full bg-os-elevated border border-os-border rounded
            px-3 py-2 text-xs font-mono text-tx-primary
            placeholder:text-tx-muted resize-y outline-none
            focus:border-accent/50 transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed
          "
        />
      </div>

      {/* Toggles */}
      <div className="space-y-2.5">
        <label className="flex items-center gap-3 cursor-pointer group">
          <input
            type="checkbox"
            checked={runTests}
            onChange={e => setRunTests(e.target.checked)}
            disabled={busy || phase === 'success'}
            className="w-3.5 h-3.5 accent-[#5b9cf6] disabled:cursor-not-allowed"
          />
          <div>
            <span className="text-xs font-mono text-tx-secondary group-hover:text-tx-primary transition-colors">
              Run tests
            </span>
            <span className="text-[10px] font-mono text-tx-muted ml-2">
              (pytest -q, 60s timeout)
            </span>
          </div>
        </label>

        <label className="flex items-center gap-3 cursor-pointer group">
          <input
            type="checkbox"
            checked={allowNeedsReview}
            onChange={e => setAllowNeedsReview(e.target.checked)}
            disabled={busy || phase === 'success'}
            className="w-3.5 h-3.5 accent-[#5b9cf6] disabled:cursor-not-allowed"
          />
          <div>
            <span className="text-xs font-mono text-tx-secondary group-hover:text-tx-primary transition-colors">
              Allow needs_review outcome
            </span>
          </div>
        </label>
      </div>

      {/* Validation error */}
      {validationError && (
        <p className="text-[11px] font-mono text-err">{validationError}</p>
      )}

      {/* Submit error */}
      {phase === 'error' && submitError && (
        <div className="px-3 py-2 rounded bg-err/10 border border-err/30">
          <p className="text-[11px] font-mono text-err">{submitError}</p>
        </div>
      )}

      {/* Success state */}
      {phase === 'success' && lastExecId && (
        <div className="px-3 py-2 rounded bg-ok/10 border border-ok/30 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-ok flex-shrink-0" />
          <p className="text-[11px] font-mono text-ok">
            Execution created — <span className="text-tx-secondary">{lastExecId}</span>
            <span className="text-tx-muted ml-2">Navigating…</span>
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={busy || phase === 'success'}
          className="
            px-4 py-2 text-xs font-mono rounded border
            bg-accent/15 border-accent/30 text-accent
            hover:bg-accent/25 transition-colors
            disabled:opacity-50 disabled:cursor-not-allowed
          "
        >
          {busy ? 'Executing…' : 'Run CODE execution'}
        </button>

        {(phase === 'error' || phase === 'success') && (
          <button
            type="button"
            onClick={handleReset}
            className="
              px-3 py-2 text-xs font-mono rounded border
              border-os-border text-tx-muted
              hover:text-tx-secondary hover:border-os-border-hi transition-colors
            "
          >
            Reset
          </button>
        )}
      </div>
    </form>
  )
}

// ── Placeholder slots (M5+) ───────────────────────────────────────────────────

const FUTURE_SLOTS = [
  { label: 'WORK Create',   description: 'Crear tarea institucional',        sprint: 'M5' },
  { label: 'WORK Query',    description: 'Consultar tareas y proyectos',      sprint: 'M5' },
  { label: 'FIN Plan',      description: 'Crear o revisar plan financiero',   sprint: 'M5' },
  { label: 'Health Check',  description: 'Forzar comprobación del sistema',   sprint: 'M5' },
  { label: 'New Session',   description: 'Iniciar sesión de conversación',    sprint: 'M5' },
]

// ── View ──────────────────────────────────────────────────────────────────────

export function ActionsView() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto p-6 space-y-8">

        {/* CODE Run — active */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <div className="w-7 h-7 rounded bg-accent/15 border border-accent/25 flex items-center justify-center">
              <span className="text-sm font-mono text-accent">{'>'}</span>
            </div>
            <div>
              <p className="text-sm font-mono font-medium text-tx-primary">CODE Run</p>
              <p className="text-[10px] font-mono text-tx-muted">Ejecutar código en el runner local</p>
            </div>
            <span className="ml-auto text-[9px] font-mono border border-ok/30 text-ok px-1.5 py-0.5 rounded">
              M4 · live
            </span>
          </div>

          <div className="bg-os-surface border border-os-border rounded-lg p-5">
            <CodeRunForm />
          </div>
        </section>

        {/* Future slots */}
        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Roadmap M5+
          </p>
          <div className="grid grid-cols-2 gap-2">
            {FUTURE_SLOTS.map(slot => (
              <div
                key={slot.label}
                className="px-3 py-2.5 rounded border border-os-border bg-os-surface opacity-50"
              >
                <div className="flex items-center justify-between mb-0.5">
                  <p className="text-xs font-mono text-tx-secondary">{slot.label}</p>
                  <span className="text-[9px] font-mono text-tx-muted border border-os-border px-1.5 rounded">
                    {slot.sprint}
                  </span>
                </div>
                <p className="text-[10px] font-mono text-tx-muted">{slot.description}</p>
              </div>
            ))}
          </div>
        </section>

      </div>
    </div>
  )
}
