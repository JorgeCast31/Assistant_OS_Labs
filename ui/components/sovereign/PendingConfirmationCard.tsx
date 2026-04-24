'use client'

import type { PendingConfirmation } from '@/lib/sovereign/types'
import { AuthorityArtifactCard } from './AuthorityArtifactCard'

interface PendingConfirmationCardProps {
  confirmation: PendingConfirmation
  onConfirm?: () => void
  onCancel?: () => void
  isProcessing?: boolean
}

export function PendingConfirmationCard({ 
  confirmation, 
  onConfirm, 
  onCancel,
  isProcessing = false,
}: PendingConfirmationCardProps) {
  const hasExpiry = confirmation.expires_at != null
  const expiresAt = hasExpiry ? new Date(confirmation.expires_at!) : null

  return (
    <div className="rounded-xl border-2 border-amber-500/40 bg-gradient-to-br from-amber-500/10 to-amber-600/5 p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className="w-6 h-6 rounded-lg bg-amber-500/20 flex items-center justify-center">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-amber-400">
            <path d="M7 1L12 4V10L7 13L2 10V4L7 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            <path d="M7 5V7.5M7 9V9.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
        <span className="text-sm font-mono font-semibold text-amber-400">
          Confirmation Required
        </span>
        {hasExpiry && expiresAt && (
          <span className="ml-auto text-[9px] font-mono text-amber-400/60">
            Expires: {expiresAt.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {/* Prompt */}
      <p className="text-sm font-mono text-tx-primary leading-relaxed mb-3">
        {confirmation.prompt}
      </p>

      {/* Artifact Preview */}
      {confirmation.artifact && (
        <div className="mb-4">
          <AuthorityArtifactCard artifact={confirmation.artifact} />
        </div>
      )}

      {/* Actions */}
      {(onConfirm || onCancel) && (
        <div className="flex items-center gap-3 pt-3 border-t border-amber-500/20">
          <button
            onClick={onCancel}
            disabled={isProcessing}
            className="flex-1 px-4 py-2.5 rounded-lg text-sm font-mono
              bg-slate-500/10 border border-slate-500/20 text-slate-400
              hover:bg-slate-500/20 hover:border-slate-500/30
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isProcessing}
            className="flex-1 px-4 py-2.5 rounded-lg text-sm font-mono font-semibold
              bg-amber-500/20 border border-amber-500/40 text-amber-400
              hover:bg-amber-500/30 hover:border-amber-500/50
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-colors"
          >
            {isProcessing ? 'Processing...' : 'Confirm Execution'}
          </button>
        </div>
      )}

      {/* Confirmation ID */}
      <div className="mt-3 pt-2 border-t border-amber-500/10">
        <span className="text-[9px] font-mono text-tx-muted">
          Confirmation ID: {confirmation.confirmation_id}
        </span>
      </div>
    </div>
  )
}
