import type { AgentPermissionProfileShape } from '@/lib/sovereign/police-types'

const agentPermissionProfileFixture: AgentPermissionProfileShape = {
  agent_id: 'agent-static-001',
  declared_capabilities: ['audit_read', 'surface_render'],
  permitted_tools: ['read_audit_records'],
  permitted_environments: ['local_readonly'],
  requires_review: true,
  status: 'review_scope_declared',
}

export function AgentPermissionProfilePanel() {
  const profile = agentPermissionProfileFixture

  return (
    <section className="rounded-lg border border-os-border bg-os-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-xs font-mono text-tx-secondary uppercase tracking-wider">
          Agent Scope Profile
        </p>
      </div>

      <div className="px-4 py-3 border-b border-os-border">
        <p className="text-[10px] font-mono text-tx-muted leading-relaxed">
          AgentPermissionProfile is scope-only and does not grant execution permission.
        </p>
        <p className="text-[10px] font-mono text-tx-muted mt-1">
          Read-only surface. No mutation controls.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 px-4 py-3">
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Status</p>
          <p className="text-sm font-mono text-tx-primary">{profile.status}</p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Review</p>
          <p className="text-sm font-mono text-tx-secondary">
            {profile.requires_review ? 'required' : 'not required'}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Agent ID</p>
          <p className="text-sm font-mono text-tx-secondary break-words">{profile.agent_id}</p>
        </div>
        <div className="col-span-2 md:col-span-4">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Capabilities</p>
          <ul className="mt-1 space-y-1">
            {profile.declared_capabilities.map((capability) => (
              <li key={capability} className="text-sm font-mono text-tx-secondary break-words">
                {capability}
              </li>
            ))}
          </ul>
        </div>
        <div className="col-span-2">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Tools</p>
          <ul className="mt-1 space-y-1">
            {profile.permitted_tools.map((tool) => (
              <li key={tool} className="text-sm font-mono text-tx-secondary break-words">
                {tool}
              </li>
            ))}
          </ul>
        </div>
        <div className="col-span-2">
          <p className="text-[10px] font-mono text-tx-muted uppercase tracking-wider">Environments</p>
          <ul className="mt-1 space-y-1">
            {profile.permitted_environments.map((environment) => (
              <li key={environment} className="text-sm font-mono text-tx-secondary break-words">
                {environment}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
