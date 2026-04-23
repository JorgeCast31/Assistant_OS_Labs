import { create } from 'zustand';
import {
  WorldState,
  AgentDomain,
  EntityState,
  EscalationRequest,
  ConversationMessage,
  AGENT_ZONES,
  MSOEntity,
  AgentEntity,
} from '@/lib/sovereign-types';

// Initial MSO entity
const initialMSO: MSOEntity = {
  id: 'mso-sovereign',
  name: 'Master System Orchestrator',
  domain: 'MSO',
  state: 'idle',
  authorityLevel: 'sovereign',
  position: { x: 50, y: 50 },
  activeDecisions: [],
  systemHealth: 'optimal',
};

// Initial agent entities
const createInitialAgent = (domain: AgentDomain): AgentEntity => ({
  id: `agent-${domain.toLowerCase()}`,
  name: `${domain} Agent`,
  domain,
  state: 'idle',
  authorityLevel: 'delegated',
  position: getAgentPosition(domain),
  parentMSO: 'mso-sovereign',
  capabilities: getAgentCapabilities(domain),
  activeWorkItems: 0,
});

function getAgentPosition(domain: AgentDomain): { x: number; y: number } {
  const positions: Record<AgentDomain, { x: number; y: number }> = {
    CODE: { x: 20, y: 20 },
    WORK: { x: 80, y: 20 },
    FIN: { x: 20, y: 80 },
    HOST: { x: 80, y: 80 },
  };
  return positions[domain];
}

function getAgentCapabilities(domain: AgentDomain): string[] {
  const capabilities: Record<AgentDomain, string[]> = {
    CODE: ['code_generation', 'debugging', 'refactoring', 'code_review'],
    WORK: ['task_management', 'scheduling', 'planning', 'reminders'],
    FIN: ['budget_tracking', 'transaction_analysis', 'financial_reports'],
    HOST: ['system_monitoring', 'log_analysis', 'health_checks', 'deployments'],
  };
  return capabilities[domain];
}

interface SovereignStore extends WorldState {
  // Navigation actions
  setViewMode: (mode: 'world' | 'focused' | 'chat') => void;
  focusEntity: (entity: AgentDomain | 'MSO' | null) => void;
  navigateToZone: (zone: AgentDomain | 'MSO') => void;

  // Entity state actions
  setEntityState: (entityId: string, state: EntityState) => void;
  setMSOState: (state: EntityState) => void;
  setAgentState: (domain: AgentDomain, state: EntityState) => void;

  // Escalation actions
  createEscalation: (
    fromAgent: AgentDomain,
    reason: string,
    priority: EscalationRequest['priority'],
    context: string,
    requiredAuthority: string
  ) => void;
  resolveEscalation: (id: string, outcome: 'approved' | 'denied') => void;

  // Conversation actions
  addMessage: (message: Omit<ConversationMessage, 'id' | 'timestamp'>) => void;
  clearConversation: () => void;

  // Active entity actions
  setActiveEntity: (entity: AgentDomain | 'MSO' | null) => void;
}

export const useSovereignStore = create<SovereignStore>((set, get) => ({
  // Initial state
  mso: initialMSO,
  agents: {
    CODE: createInitialAgent('CODE'),
    WORK: createInitialAgent('WORK'),
    FIN: createInitialAgent('FIN'),
    HOST: createInitialAgent('HOST'),
  },
  zones: AGENT_ZONES,
  interaction: {
    activeEntity: null,
    activeZone: null,
    conversationThread: [],
    pendingEscalations: [],
  },
  viewMode: 'world',
  focusedEntity: null,

  // Navigation actions
  setViewMode: (mode) => set({ viewMode: mode }),

  focusEntity: (entity) =>
    set({
      focusedEntity: entity,
      viewMode: entity ? 'focused' : 'world',
    }),

  navigateToZone: (zone) =>
    set((state) => ({
      focusedEntity: zone,
      viewMode: 'focused',
      interaction: {
        ...state.interaction,
        activeZone: zone,
        activeEntity:
          zone === 'MSO' ? state.mso : zone ? state.agents[zone] : null,
      },
    })),

  // Entity state actions
  setEntityState: (entityId, newState) =>
    set((state) => {
      if (entityId === 'mso-sovereign') {
        return { mso: { ...state.mso, state: newState } };
      }
      const domain = Object.keys(state.agents).find(
        (d) => state.agents[d as AgentDomain].id === entityId
      ) as AgentDomain | undefined;
      if (domain) {
        return {
          agents: {
            ...state.agents,
            [domain]: { ...state.agents[domain], state: newState },
          },
        };
      }
      return state;
    }),

  setMSOState: (state) =>
    set((s) => ({ mso: { ...s.mso, state } })),

  setAgentState: (domain, newState) =>
    set((state) => ({
      agents: {
        ...state.agents,
        [domain]: { ...state.agents[domain], state: newState },
      },
    })),

  // Escalation actions
  createEscalation: (fromAgent, reason, priority, context, requiredAuthority) =>
    set((state) => {
      const escalation: EscalationRequest = {
        id: `esc-${Date.now()}`,
        fromAgent,
        reason,
        priority,
        timestamp: new Date(),
        context,
        requiredAuthority,
        status: 'pending',
      };
      return {
        mso: {
          ...state.mso,
          activeDecisions: [...state.mso.activeDecisions, escalation],
          state: 'thinking',
        },
        agents: {
          ...state.agents,
          [fromAgent]: { ...state.agents[fromAgent], state: 'escalating' },
        },
        interaction: {
          ...state.interaction,
          pendingEscalations: [
            ...state.interaction.pendingEscalations,
            escalation,
          ],
        },
      };
    }),

  resolveEscalation: (id, outcome) =>
    set((state) => {
      const escalation = state.mso.activeDecisions.find((e) => e.id === id);
      if (!escalation) return state;

      const updatedDecisions = state.mso.activeDecisions.filter(
        (e) => e.id !== id
      );
      const updatedPending = state.interaction.pendingEscalations.filter(
        (e) => e.id !== id
      );

      return {
        mso: {
          ...state.mso,
          activeDecisions: updatedDecisions,
          state: updatedDecisions.length > 0 ? 'thinking' : 'idle',
        },
        agents: {
          ...state.agents,
          [escalation.fromAgent]: {
            ...state.agents[escalation.fromAgent],
            state: outcome === 'approved' ? 'executing' : 'idle',
          },
        },
        interaction: {
          ...state.interaction,
          pendingEscalations: updatedPending,
        },
      };
    }),

  // Conversation actions
  addMessage: (message) =>
    set((state) => ({
      interaction: {
        ...state.interaction,
        conversationThread: [
          ...state.interaction.conversationThread,
          {
            ...message,
            id: `msg-${Date.now()}`,
            timestamp: new Date(),
          },
        ],
      },
    })),

  clearConversation: () =>
    set((state) => ({
      interaction: {
        ...state.interaction,
        conversationThread: [],
      },
    })),

  // Active entity actions
  setActiveEntity: (entity) =>
    set((state) => ({
      interaction: {
        ...state.interaction,
        activeZone: entity,
        activeEntity:
          entity === 'MSO'
            ? state.mso
            : entity
            ? state.agents[entity]
            : null,
      },
    })),
}));
