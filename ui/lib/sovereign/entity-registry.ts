// UI Cognitive Entity Registry v0
// Static configuration mapping UI entities to their backend actors, capabilities, and boundaries.
// v1 will be driven by a backend /system/entity-registry endpoint.

export type CognitiveCapability =
  | 'observe_state'
  | 'converse'
  | 'prepare_action'
  | 'confirm_action'
  | 'execute_action'
  | 'inspect_trace'
  | 'inspect_raw'

export type CognitiveBoundary =
  | 'no_direct_execution'
  | 'no_token_issuance'
  | 'no_policy_override'
  | 'read_only_surface'
  | 'display_only'

export type ExecutionPolicy =
  | 'cognitive_only'
  | 'governed_execution'
  | 'read_only'
  | 'display_only'

export type ProviderBinding =
  | 'seat_provider'
  | 'orchestrator'
  | 'static'
  | 'none'

export interface CognitiveEntityDefinition {
  id: string
  label: string
  description: string
  surface: string | null
  backend_endpoint: string | null
  status_endpoint: string | null
  cognitive_actor: string
  provider_binding: ProviderBinding
  capabilities: CognitiveCapability[]
  boundaries: CognitiveBoundary[]
  provenance_required: boolean
  raw_trace_required: boolean
  execution_policy: ExecutionPolicy
}

export const COGNITIVE_ENTITY_REGISTRY: CognitiveEntityDefinition[] = [
  {
    id: 'main_chat',
    label: 'Main Chat',
    description: 'Conversational interface for WORK/CODE/FIN/HOST tasks via orchestrator with full governance.',
    surface: 'assistant_chat',
    backend_endpoint: '/chat/process',
    status_endpoint: '/system/runtime-state',
    cognitive_actor: 'AssistantOS Orchestrator',
    provider_binding: 'orchestrator',
    capabilities: ['observe_state', 'converse', 'prepare_action', 'confirm_action', 'execute_action'],
    boundaries: ['no_token_issuance', 'no_policy_override'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'governed_execution',
  },
  {
    id: 'mso_console',
    label: 'MSO Console',
    description: 'Sovereign cognitive conversational surface. Full Economic Cognition chain. Cannot execute directly.',
    surface: 'mso_direct',
    backend_endpoint: '/chat/process',
    status_endpoint: '/mso/state',
    cognitive_actor: 'MSO Economic Cognition (seat_provider + Vault + Session History)',
    provider_binding: 'seat_provider',
    capabilities: ['observe_state', 'converse', 'prepare_action', 'inspect_trace', 'inspect_raw'],
    boundaries: ['no_direct_execution', 'no_token_issuance', 'no_policy_override'],
    provenance_required: true,
    raw_trace_required: true,
    execution_policy: 'cognitive_only',
  },
  {
    id: 'mso_provider_selector',
    label: 'MSO Provider Selector',
    description: 'Displays the currently seated cognitive provider. Read-only in v0.',
    surface: null,
    backend_endpoint: '/mso/seat/provider',
    status_endpoint: '/mso/seat/provider',
    cognitive_actor: 'seat_model_provider_registry',
    provider_binding: 'seat_provider',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'mso_raw_trace',
    label: 'MSO Raw Trace',
    description: 'Per-message full backend provenance inspector.',
    surface: null,
    backend_endpoint: null,
    status_endpoint: null,
    cognitive_actor: 'Passthrough — no backend call',
    provider_binding: 'none',
    capabilities: ['inspect_trace', 'inspect_raw'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: true,
    raw_trace_required: true,
    execution_policy: 'display_only',
  },
  {
    id: 'mission_control',
    label: 'Mission Control',
    description: 'Read-only situation room. Polls MSO seat, queues, authority. No execution surface.',
    surface: null,
    backend_endpoint: null,
    status_endpoint: '/mso/state',
    cognitive_actor: 'Multiple polling readers: prepared_action_queue, confirm_flow, authority, seat_provider',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'confirm_queue',
    label: 'Confirm Queue',
    description: 'Observability view of confirm-pending entries.',
    surface: null,
    backend_endpoint: '/confirm/pending',
    status_endpoint: '/confirm/pending',
    cognitive_actor: 'confirm_flow module',
    provider_binding: 'none',
    capabilities: ['observe_state', 'inspect_trace'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'prepared_actions',
    label: 'Prepared Actions',
    description: 'Manual review queue with full authority timeline.',
    surface: null,
    backend_endpoint: '/mso/prepared-actions/pending',
    status_endpoint: '/mso/prepared-actions/pending',
    cognitive_actor: 'prepared_action_queue module',
    provider_binding: 'none',
    capabilities: ['observe_state', 'inspect_trace'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'authority_matrix',
    label: 'Authority Matrix',
    description: 'Capability posture view. Shows allow/deny/confirm-only counts.',
    surface: null,
    backend_endpoint: '/mso/authority/status',
    status_endpoint: '/mso/authority/status',
    cognitive_actor: 'authority module',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'agent_registry',
    label: 'Agent Registry',
    description: 'Live list of registered agents. No operational console in v0.',
    surface: null,
    backend_endpoint: '/agents/registry',
    status_endpoint: '/agents/registry',
    cognitive_actor: 'build_agents_registry_response()',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'no_direct_execution'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'read_only',
  },
  {
    id: 'system_capabilities',
    label: 'System Capabilities',
    description: 'System capability and feature flag metadata.',
    surface: null,
    backend_endpoint: '/system/capabilities',
    status_endpoint: '/system/capabilities',
    cognitive_actor: 'build_system_capabilities_response()',
    provider_binding: 'none',
    capabilities: ['observe_state'],
    boundaries: ['read_only_surface', 'display_only'],
    provenance_required: false,
    raw_trace_required: false,
    execution_policy: 'display_only',
  },
]

export function getEntity(id: string): CognitiveEntityDefinition | undefined {
  return COGNITIVE_ENTITY_REGISTRY.find((e) => e.id === id)
}

export function hasCapability(entity: CognitiveEntityDefinition, cap: CognitiveCapability): boolean {
  return entity.capabilities.includes(cap)
}
