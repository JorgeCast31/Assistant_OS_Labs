import type { SovereignMessage, ExecutionStatus, GovernanceTrace } from '@/lib/sovereign/types'

function executionStatusClass(status: ExecutionStatus): string {
  switch (status) {
    case 'real':    return 'text-ok border-ok/30 bg-ok/10'
    case 'stub':    return 'text-warn border-warn/30 bg-warn/10'
    case 'partial': return 'text-warn border-warn/30 bg-warn/10'
    case 'unavailable': return 'text-tx-muted border-os-border bg-os-base'
  }
}

function governanceClass(decision: GovernanceTrace['decision']): string {
  switch (decision) {
    case 'ALLOW':                return 'text-ok border-ok/30 bg-ok/10'
    case 'BLOCK':                return 'text-error border-error/30 bg-error/10'
    case 'REQUIRE_CONFIRMATION': return 'text-warn border-warn/30 bg-warn/10'
    case 'DEGRADED':             return 'text-warn border-warn/30 bg-warn/10'
  }
}

function MessageBadges({ msg }: { msg: SovereignMessage }) {
  const hasStatus = msg.executionStatus !== undefined
  const hasTrace  = msg.governanceTrace !== undefined

  if (!hasStatus && !hasTrace) return null

  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {hasStatus && (
        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-mono uppercase tracking-wider ${executionStatusClass(msg.executionStatus!)}`}>
          {msg.executionStatus}
        </span>
      )}
      {hasTrace && (
        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-mono uppercase tracking-wider ${governanceClass(msg.governanceTrace!.decision)}`}>
          {msg.governanceTrace!.decision}
          {msg.governanceTrace!.risk_level && (
            <span className="ml-1 normal-case opacity-70">{msg.governanceTrace!.risk_level}</span>
          )}
        </span>
      )}
    </div>
  )
}

export function MSOChatTranscript({ messages }: { messages: SovereignMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <p className="text-xs font-mono text-tx-muted">
          No messages yet. Send a message to start the MSO conversation.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {messages.map((msg) => {
        const isUser = msg.role === 'user'
        return (
          <div
            key={msg.id}
            className={`flex flex-col ${isUser ? 'items-end' : 'items-start'}`}
          >
            <div className="mb-0.5 flex items-center gap-2">
              <span className="text-[9px] font-mono uppercase tracking-widest text-tx-muted">
                {msg.role}
              </span>
              <span className="text-[9px] font-mono text-tx-muted">
                {new Date(msg.timestamp).toLocaleTimeString('es', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-xs font-mono ${
                isUser
                  ? 'bg-accent/10 border border-accent/20 text-tx-primary'
                  : 'bg-os-surface border border-os-border text-tx-primary'
              }`}
            >
              <p className="leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              {!isUser && <MessageBadges msg={msg} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}
