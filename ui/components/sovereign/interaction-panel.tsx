'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import {
  AgentDomain,
  AGENT_ZONES,
  ConversationMessage,
} from '@/lib/sovereign-types';
import {
  Send,
  X,
  Shield,
  Code2,
  Briefcase,
  DollarSign,
  Server,
  AlertTriangle,
  CheckCircle,
  XCircle,
  MessageSquare,
  Zap,
} from 'lucide-react';

const domainIcons: Record<AgentDomain | 'MSO', React.ElementType> = {
  CODE: Code2,
  WORK: Briefcase,
  FIN: DollarSign,
  HOST: Server,
  MSO: Shield,
};

interface MessageBubbleProps {
  message: ConversationMessage;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.from === 'USER';
  const isMSO = message.from === 'MSO';
  const Icon = message.from === 'USER' ? MessageSquare : domainIcons[message.from];

  const getMessageStyle = () => {
    if (isUser) return 'bg-blue-600 text-white ml-auto';
    if (isMSO) return 'bg-slate-700 text-white border border-slate-600';
    const zone = AGENT_ZONES[message.from as AgentDomain];
    return `bg-slate-800 text-white border-l-2` + ` border-l-[${zone?.color}]`;
  };

  const getTypeIndicator = () => {
    switch (message.type) {
      case 'escalation':
        return (
          <span className="flex items-center gap-1 text-xs text-amber-400">
            <AlertTriangle className="h-3 w-3" /> Escalation
          </span>
        );
      case 'decision':
        return (
          <span
            className={`flex items-center gap-1 text-xs ${
              message.metadata?.decisionOutcome === 'approved'
                ? 'text-emerald-400'
                : 'text-red-400'
            }`}
          >
            {message.metadata?.decisionOutcome === 'approved' ? (
              <CheckCircle className="h-3 w-3" />
            ) : (
              <XCircle className="h-3 w-3" />
            )}
            Decision
          </span>
        );
      case 'action':
        return (
          <span className="flex items-center gap-1 text-xs text-cyan-400">
            <Zap className="h-3 w-3" /> Action
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* Avatar */}
      {!isUser && (
        <div
          className={`h-8 w-8 rounded-full flex items-center justify-center flex-shrink-0 ${
            isMSO ? 'bg-slate-600' : 'bg-slate-700'
          }`}
          style={
            !isMSO && message.from !== 'USER'
              ? { backgroundColor: `${AGENT_ZONES[message.from as AgentDomain]?.color}30` }
              : {}
          }
        >
          <Icon className="h-4 w-4 text-white" />
        </div>
      )}

      {/* Message content */}
      <div className={`max-w-[75%] ${isUser ? 'text-right' : ''}`}>
        {!isUser && (
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-slate-400">
              {isMSO ? 'MSO' : AGENT_ZONES[message.from as AgentDomain]?.label}
            </span>
            {getTypeIndicator()}
          </div>
        )}
        <div className={`px-3 py-2 rounded-lg ${getMessageStyle()}`}>
          <p className="text-sm">{message.content}</p>
        </div>
        <p className="text-[10px] text-slate-500 mt-1">
          {new Date(message.timestamp).toLocaleTimeString()}
        </p>
      </div>
    </motion.div>
  );
}

interface InteractionPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function InteractionPanel({ isOpen, onClose }: InteractionPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    interaction,
    focusedEntity,
    addMessage,
    mso,
    agents,
    createEscalation,
    setAgentState,
    setMSOState,
  } = useSovereignStore();

  const activeEntity =
    focusedEntity === 'MSO' ? mso : focusedEntity ? agents[focusedEntity] : null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [interaction.conversationThread]);

  const handleSend = () => {
    if (!input.trim() || !focusedEntity) return;

    // Add user message
    addMessage({
      from: 'USER',
      content: input,
      type: 'message',
    });

    // Simulate agent response
    const simulateResponse = () => {
      if (focusedEntity === 'MSO') {
        setMSOState('thinking');
        setTimeout(() => {
          addMessage({
            from: 'MSO',
            content: `Acknowledged. Processing your request through the sovereign system. All agent activities are being monitored.`,
            type: 'message',
          });
          setMSOState('idle');
        }, 1500);
      } else {
        setAgentState(focusedEntity, 'thinking');
        setTimeout(() => {
          // Check if request might need escalation (simulated)
          const needsEscalation = input.toLowerCase().includes('delete') ||
            input.toLowerCase().includes('deploy') ||
            input.toLowerCase().includes('production');

          if (needsEscalation) {
            setAgentState(focusedEntity, 'escalating');
            addMessage({
              from: focusedEntity,
              content: `This action requires elevated permissions. Escalating to MSO for approval...`,
              type: 'escalation',
            });
            createEscalation(
              focusedEntity,
              `User requested: "${input.slice(0, 50)}..."`,
              'high',
              input,
              'sovereign_approval'
            );
          } else {
            addMessage({
              from: focusedEntity,
              content: `Processing your request within my delegated authority. I'll handle this directly.`,
              type: 'message',
            });
            setAgentState(focusedEntity, 'executing');
            setTimeout(() => setAgentState(focusedEntity, 'idle'), 2000);
          }
        }, 1000);
      }
    };

    simulateResponse();
    setInput('');
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, y: 50 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 50 }}
          className="absolute bottom-4 left-4 right-4 md:left-auto md:right-4 md:w-96
            bg-slate-900/95 backdrop-blur-xl rounded-xl border border-slate-700/50
            shadow-2xl shadow-black/50 overflow-hidden"
          style={{ maxHeight: 'calc(100vh - 8rem)' }}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
            <div className="flex items-center gap-3">
              {activeEntity && (
                <div
                  className="h-10 w-10 rounded-full flex items-center justify-center"
                  style={{
                    backgroundColor:
                      focusedEntity === 'MSO'
                        ? 'rgb(71, 85, 105)'
                        : `${AGENT_ZONES[focusedEntity as AgentDomain].color}30`,
                  }}
                >
                  {focusedEntity && (
                    (() => {
                      const Icon = domainIcons[focusedEntity];
                      return <Icon className="h-5 w-5 text-white" />;
                    })()
                  )}
                </div>
              )}
              <div>
                <h3 className="text-sm font-semibold text-white">
                  {focusedEntity === 'MSO'
                    ? 'Master System Orchestrator'
                    : focusedEntity
                    ? AGENT_ZONES[focusedEntity].label
                    : 'Select an entity'}
                </h3>
                <p className="text-xs text-slate-400">
                  {activeEntity
                    ? `Authority: ${activeEntity.authorityLevel}`
                    : 'Navigate to interact'}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <X className="h-4 w-4 text-slate-400" />
            </button>
          </div>

          {/* Messages */}
          <div className="h-64 overflow-y-auto p-4 space-y-4">
            {interaction.conversationThread.length === 0 ? (
              <div className="h-full flex items-center justify-center text-center">
                <div className="space-y-2">
                  <MessageSquare className="h-8 w-8 text-slate-600 mx-auto" />
                  <p className="text-sm text-slate-500">
                    {focusedEntity
                      ? `Start a conversation with ${
                          focusedEntity === 'MSO' ? 'MSO' : AGENT_ZONES[focusedEntity].label
                        }`
                      : 'Select an entity to interact'}
                  </p>
                </div>
              </div>
            ) : (
              <>
                {interaction.conversationThread.map((msg) => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input */}
          <div className="p-4 border-t border-slate-700/50">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={
                  focusedEntity
                    ? `Message ${focusedEntity === 'MSO' ? 'MSO' : AGENT_ZONES[focusedEntity].label}...`
                    : 'Select an entity first...'
                }
                disabled={!focusedEntity}
                className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2
                  text-sm text-white placeholder-slate-500
                  focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500
                  disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                onClick={handleSend}
                disabled={!focusedEntity || !input.trim()}
                className="p-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 
                  disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                <Send className="h-5 w-5 text-white" />
              </motion.button>
            </div>
            {focusedEntity && focusedEntity !== 'MSO' && (
              <p className="text-[10px] text-slate-500 mt-2">
                Sensitive actions will be escalated to MSO for approval
              </p>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
