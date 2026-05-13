export function MSOInvariantStrip() {
  return (
    <div
      role="status"
      aria-label="MSO execution invariants"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-warn/30 bg-warn/5 px-4 py-2 font-mono text-[10px] text-warn"
    >
      <span>surface: mso_direct</span>
      <span className="text-tx-muted">·</span>
      <span>execution_allowed=false</span>
      <span className="text-tx-muted">·</span>
      <span>can_execute_now=false</span>
      <span className="text-tx-muted">·</span>
      <span className="text-tx-secondary">MSO coordinates; it does not execute directly.</span>
    </div>
  )
}
