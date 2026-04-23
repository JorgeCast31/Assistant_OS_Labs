'use client';

import { motion } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import { AgentDomain, AGENT_ZONES } from '@/lib/sovereign-types';
import { AgentNode } from './agent-node';

interface AgentZoneProps {
  domain: AgentDomain;
  onEnter?: () => void;
}

export function AgentZone({ domain, onEnter }: AgentZoneProps) {
  const { agents, navigateToZone, focusedEntity } = useSovereignStore();
  const zone = AGENT_ZONES[domain];
  const agent = agents[domain];
  const isActive = focusedEntity === domain;

  const positionClasses: Record<string, string> = {
    'top-left': 'top-0 left-0',
    'top-right': 'top-0 right-0',
    'bottom-left': 'bottom-0 left-0',
    'bottom-right': 'bottom-0 right-0',
  };

  const handleZoneClick = () => {
    navigateToZone(domain);
    onEnter?.();
  };

  return (
    <motion.div
      className={`absolute ${positionClasses[zone.position]} 
        w-[45%] h-[42%] rounded-2xl
        cursor-pointer overflow-hidden
        transition-all duration-300`}
      onClick={handleZoneClick}
      whileHover={{ scale: 1.02 }}
      animate={{
        opacity: isActive ? 1 : 0.7,
      }}
    >
      {/* Zone background */}
      <div
        className="absolute inset-0 rounded-2xl border border-white/5"
        style={{
          background: `linear-gradient(135deg, ${zone.color}08, ${zone.color}03)`,
        }}
      />

      {/* Zone hover highlight */}
      <motion.div
        className="absolute inset-0 rounded-2xl"
        style={{
          background: `radial-gradient(circle at center, ${zone.color}15, transparent 70%)`,
        }}
        initial={{ opacity: 0 }}
        whileHover={{ opacity: 1 }}
      />

      {/* Active indicator border */}
      {isActive && (
        <motion.div
          className="absolute inset-0 rounded-2xl border-2"
          style={{ borderColor: zone.color }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.5 }}
        />
      )}

      {/* Zone content */}
      <div className="relative h-full flex flex-col items-center justify-center p-4">
        {/* Agent node */}
        <AgentNode domain={domain} size="lg" showDetails={true} />

        {/* Zone label (bottom) */}
        <div className="absolute bottom-4 left-4 right-4">
          <p className="text-xs text-slate-500 text-center truncate">
            {zone.description}
          </p>
        </div>

        {/* Capability indicators */}
        <div className="absolute top-4 right-4 flex flex-col gap-1">
          {agent.capabilities.slice(0, 3).map((cap, i) => (
            <motion.div
              key={cap}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 0.5, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className="px-2 py-0.5 rounded text-[10px] text-slate-400 bg-slate-800/50"
            >
              {cap.replace(/_/g, ' ')}
            </motion.div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
