'use client'

import type { AuthorityArtifact } from '@/lib/sovereign/types'

interface AuthorityArtifactCardProps {
  artifact: AuthorityArtifact
}

export function AuthorityArtifactCard({ artifact }: AuthorityArtifactCardProps) {
  const typeIcons = {
    plan: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2 3H10M2 6H8M2 9H6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    ),
    command: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    script: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M4 3L2 6L4 9M8 3L10 6L8 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    action: (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <circle cx="6" cy="6" r="4" stroke="currentColor" strokeWidth="1.2" />
        <path d="M6 4V7L8 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  }

  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-amber-400">
            {typeIcons[artifact.type] || typeIcons.action}
          </span>
          <span className="text-xs font-mono font-semibold text-amber-400 uppercase tracking-wider">
            Authority Artifact
          </span>
        </div>
        <div className="flex items-center gap-2">
          {artifact.requires_auth && (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">
              AUTH REQUIRED
            </span>
          )}
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-500/20 text-slate-400 uppercase">
            {artifact.type}
          </span>
        </div>
      </div>

      <p className="text-sm font-mono text-tx-primary leading-relaxed">
        {artifact.summary}
      </p>

      {artifact.details && Object.keys(artifact.details).length > 0 && (
        <div className="mt-2 pt-2 border-t border-amber-500/10">
          <pre className="text-[10px] font-mono text-tx-secondary overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(artifact.details, null, 2)}
          </pre>
        </div>
      )}

      <div className="flex items-center gap-3 mt-2 pt-2 border-t border-amber-500/10">
        <span className="text-[9px] font-mono text-tx-muted">
          ID: {artifact.artifact_id}
        </span>
        <span className="text-[9px] font-mono text-tx-muted">
          {new Date(artifact.timestamp).toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })}
        </span>
      </div>
    </div>
  )
}
