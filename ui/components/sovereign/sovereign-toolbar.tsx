'use client';

import { motion } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import { AgentDomain, AGENT_ZONES } from '@/lib/sovereign-types';
import {
  Globe,
  MessageSquare,
  Shield,
  Code2,
  Briefcase,
  DollarSign,
  Server,
  AlertCircle,
} from 'lucide-react';

const domainIcons: Record<AgentDomain, React.ElementType> = {
  CODE: Code2,
  WORK: Briefcase,
  FIN: DollarSign,
  HOST: Server,
};

interface SovereignToolbarProps {
  onToggleChat: () => void;
  isChatOpen: boolean;
}

export function SovereignToolbar({ onToggleChat, isChatOpen }: SovereignToolbarProps) {
  const {
    viewMode,
    setViewMode,
    focusedEntity,
    navigateToZone,
    mso,
    agents,
  } = useSovereignStore();

  const hasPendingEscalations = mso.activeDecisions.length > 0;
  const domains: AgentDomain[] = ['CODE', 'WORK', 'FIN', 'HOST'];

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="absolute top-4 left-4 flex items-center gap-2 z-50"
    >
      {/* World view button */}
      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setViewMode('world')}
        className={`p-2.5 rounded-lg border transition-all ${
          viewMode === 'world' && !focusedEntity
            ? 'bg-slate-700 border-slate-500 text-white'
            : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-700/80 hover:text-white'
        }`}
        title="World View"
      >
        <Globe className="h-5 w-5" />
      </motion.button>

      {/* Divider */}
      <div className="h-6 w-px bg-slate-700" />

      {/* MSO quick access */}
      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => navigateToZone('MSO')}
        className={`relative p-2.5 rounded-lg border transition-all ${
          focusedEntity === 'MSO'
            ? 'bg-slate-600 border-slate-400 text-white'
            : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-700/80 hover:text-white'
        }`}
        title="MSO - Sovereign Authority"
      >
        <Shield className="h-5 w-5" />
        {hasPendingEscalations && (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-amber-500 
              flex items-center justify-center"
          >
            <span className="text-[10px] font-bold text-white">
              {mso.activeDecisions.length}
            </span>
          </motion.div>
        )}
      </motion.button>

      {/* Agent quick access */}
      {domains.map((domain) => {
        const Icon = domainIcons[domain];
        const zone = AGENT_ZONES[domain];
        const agent = agents[domain];
        const isActive = agent.state !== 'idle';
        const isFocused = focusedEntity === domain;

        return (
          <motion.button
            key={domain}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => navigateToZone(domain)}
            className={`relative p-2.5 rounded-lg border transition-all ${
              isFocused
                ? 'border-opacity-100 text-white'
                : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-700/80 hover:text-white'
            }`}
            style={{
              backgroundColor: isFocused ? `${zone.color}30` : undefined,
              borderColor: isFocused ? zone.color : undefined,
            }}
            title={zone.label}
          >
            <Icon className="h-5 w-5" />
            {isActive && (
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                className="absolute -top-1 -right-1 h-3 w-3 rounded-full"
                style={{ backgroundColor: zone.color }}
              />
            )}
            {agent.state === 'escalating' && (
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ repeat: Infinity, duration: 1 }}
                className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-purple-500 
                  flex items-center justify-center"
              >
                <AlertCircle className="h-3 w-3 text-white" />
              </motion.div>
            )}
          </motion.button>
        );
      })}

      {/* Divider */}
      <div className="h-6 w-px bg-slate-700" />

      {/* Chat toggle */}
      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={onToggleChat}
        className={`p-2.5 rounded-lg border transition-all ${
          isChatOpen
            ? 'bg-blue-600 border-blue-500 text-white'
            : 'bg-slate-800/80 border-slate-700 text-slate-400 hover:bg-slate-700/80 hover:text-white'
        }`}
        title="Toggle Chat"
      >
        <MessageSquare className="h-5 w-5" />
      </motion.button>
    </motion.div>
  );
}
