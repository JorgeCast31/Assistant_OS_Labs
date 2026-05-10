'use client'

export function ExecutionNotOpenPanel() {
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
      <p className="text-[11px] font-mono font-semibold uppercase tracking-wider text-amber-300">
        Why execution is not open yet
      </p>
      <ul className="mt-3 space-y-2">
        <li className="flex gap-2 text-xs font-mono text-tx-primary">
          <span className="text-amber-300">-</span>
          <span>CODE/docs pilot harness is not active yet.</span>
        </li>
        <li className="flex gap-2 text-xs font-mono text-tx-primary">
          <span className="text-amber-300">-</span>
          <span>HOST and MACHINE_OPERATOR require protected authority context.</span>
        </li>
        <li className="flex gap-2 text-xs font-mono text-tx-primary">
          <span className="text-amber-300">-</span>
          <span>OpenClaw is intentionally disabled.</span>
        </li>
        <li className="flex gap-2 text-xs font-mono text-tx-primary">
          <span className="text-amber-300">-</span>
          <span>Delegated MSO Seat cannot execute directly.</span>
        </li>
        <li className="flex gap-2 text-xs font-mono text-tx-primary">
          <span className="text-amber-300">-</span>
          <span>Temporal restrictions remain pending.</span>
        </li>
      </ul>
      <p className="mt-3 text-[10px] font-mono text-amber-200/80">
        Protected execution requires Policy + Police + AuthorizedPlan.
      </p>
    </div>
  )
}
