// Sovereign Operating Interface Types
// MSO-centric entity and interaction system

export type EntityState = 'idle' | 'thinking' | 'executing' | 'blocked' | 'escalating' | 'waiting';

export type AgentDomain = 'CODE' | 'WORK' | 'FIN' | 'HOST';

export type AuthorityLevel = 'sovereign' | 'delegated' | 'restricted';

export interface SovereignEntity {
  id: string;
  name: string;
  domain: AgentDomain | 'MSO';
  state: EntityState;
  authorityLevel: AuthorityLevel;
  position: { x: number; y: number };
  currentTask?: string;
  lastActivity?: Date;
}

export interface MSOEntity extends SovereignEntity {
  domain: 'MSO';
  authorityLevel: 'sovereign';
  activeDecisions: EscalationRequest[];
  systemHealth: 'optimal' | 'degraded' | 'critical';
}

export interface AgentEntity extends SovereignEntity {
  domain: AgentDomain;
  authorityLevel: 'delegated' | 'restricted';
  parentMSO: string;
  capabilities: string[];
  activeWorkItems: number;
}

export interface EscalationRequest {
  id: string;
  fromAgent: AgentDomain;
  reason: string;
  priority: 'low' | 'medium' | 'high' | 'critical';
  timestamp: Date;
  context: string;
  requiredAuthority: string;
  status: 'pending' | 'reviewing' | 'approved' | 'denied';
}

export interface AgentZone {
  domain: AgentDomain;
  label: string;
  description: string;
  color: string;
  accentColor: string;
  icon: string;
  position: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
}

export interface InteractionContext {
  activeEntity: SovereignEntity | null;
  activeZone: AgentDomain | 'MSO' | null;
  conversationThread: ConversationMessage[];
  pendingEscalations: EscalationRequest[];
}

export interface ConversationMessage {
  id: string;
  from: AgentDomain | 'MSO' | 'USER';
  content: string;
  timestamp: Date;
  type: 'message' | 'action' | 'escalation' | 'decision' | 'system';
  metadata?: {
    actionType?: string;
    escalationId?: string;
    decisionOutcome?: 'approved' | 'denied' | 'deferred';
  };
}

export interface WorldState {
  mso: MSOEntity;
  agents: Record<AgentDomain, AgentEntity>;
  zones: Record<AgentDomain, AgentZone>;
  interaction: InteractionContext;
  viewMode: 'world' | 'focused' | 'chat';
  focusedEntity: AgentDomain | 'MSO' | null;
}

// Zone configuration
export const AGENT_ZONES: Record<AgentDomain, AgentZone> = {
  CODE: {
    domain: 'CODE',
    label: 'Code Operations',
    description: 'Development, debugging, and technical execution',
    color: 'hsl(210, 100%, 50%)',
    accentColor: 'hsl(210, 100%, 70%)',
    icon: 'code',
    position: 'top-left',
  },
  WORK: {
    domain: 'WORK',
    label: 'Work Management',
    description: 'Tasks, planning, and productivity workflows',
    color: 'hsl(150, 80%, 45%)',
    accentColor: 'hsl(150, 80%, 65%)',
    icon: 'briefcase',
    position: 'top-right',
  },
  FIN: {
    domain: 'FIN',
    label: 'Financial Operations',
    description: 'Budgets, transactions, and financial analysis',
    color: 'hsl(45, 100%, 50%)',
    accentColor: 'hsl(45, 100%, 70%)',
    icon: 'dollar-sign',
    position: 'bottom-left',
  },
  HOST: {
    domain: 'HOST',
    label: 'System Operations',
    description: 'Infrastructure, monitoring, and system health',
    color: 'hsl(280, 70%, 55%)',
    accentColor: 'hsl(280, 70%, 75%)',
    icon: 'server',
    position: 'bottom-right',
  },
};

// Entity state descriptions
export const STATE_DESCRIPTIONS: Record<EntityState, string> = {
  idle: 'Awaiting instructions',
  thinking: 'Processing request',
  executing: 'Performing action',
  blocked: 'Requires escalation',
  escalating: 'Requesting authority',
  waiting: 'Awaiting response',
};
