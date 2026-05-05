'use client'

import { AuthorityMatrixPanel } from './AuthorityMatrixPanel'

export function SecurityView() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest">
            Security
          </p>
          <p className="text-xs font-mono text-tx-secondary mt-1">
            Police and authority posture for sovereign governance.
          </p>
        </div>

        <section>
          <p className="text-[10px] font-mono font-medium text-tx-muted uppercase tracking-widest mb-3">
            Authority Matrix
          </p>
          <AuthorityMatrixPanel />
        </section>
      </div>
    </div>
  )
}
