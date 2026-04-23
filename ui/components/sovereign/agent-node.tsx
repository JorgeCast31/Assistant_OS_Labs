'use client';

import { motion } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import {
  AgentDomain,
  EntityState,
  STATE_DESCRIPTIONS,
  AGENT_ZONES,
} from '@/lib/sovereign-types';
import {
  Code2,
  Briefcase,
  DollarSign,
  Server,
  Loader2,
  Activity,
  AlertTriangle,
  Clock,
  CheckCircle,
} from 'lucide-react';

const domainIcons: Record<AgentDomain, React.ElementType> = {
  CODE: Code2,
  WORK: Briefcase,
  FIN: DollarSign,
  HOST: Server,
};

const stateIcons: Record<EntityState, React.ElementType> = {
  idle: CheckCircle,
  thinking: Loader2,
  executing: Activity,
  blocked: AlertTriangle,
  escalating: AlertTriangle,
  waiting: Clock,
};

interface AgentNodeProps {
  domain: AgentDomain;
  onClick?: () => void;
  size?: 'sm' | 'md' | 'lg';
  showDetails?: boolean;
}

export function AgentNode({
  domain,
  onClick,
  size = 'md',
  showDetails = true,
}: AgentNodeProps) {
  const { agents, focusEntity, focusedEntity } = useSovereignStore();
  const agent = agents[domain];
  const zone = AGENT_ZONES[domain];
  const isFocused = focusedEntity === domain;

  const DomainIcon = domainIcons[domain];
  const StateIcon = stateIcons[agent.state];

  const sizeClasses = {
    sm: 'h-12 w-12',
    md: 'h-16 w-16',
    lg: 'h-20 w-20',
  };

  const iconSizes = {
    sm: 'h-5 w-5',
    md: 'h-7 w-7',
    lg: 'h-9 w-9',
  };

  const handleClick = () => {
    if (onClick) {
      onClick();
    } else {
      focusEntity(isFocused ? null : domain);
    }
  };

  // Get state-based styling
  const getStateStyles = () => {
    switch (agent.state) {
      case 'thinking':
        return 'ring-2 ring-blue-400/50 animate-pulse';
      case 'executing':
        return 'ring-2 ring-emerald-400/50';
      case 'blocked':
        return 'ring-2 ring-amber-400/50';
      case 'escalating':
        return 'ring-2 ring-purple-400/50 animate-pulse';
      case 'waiting':
        return 'ring-2 ring-cyan-400/50';
      default:
        return '';
    }
  };

  return (
    <div className="relative flex flex-col items-center gap-2">
      {/* Connection line to MSO (visual indicator) */}
      {agent.state === 'escalating' && (
        <motion.div
          className="absolute inset-0 pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <motion.div
            className="absolute top-1/2 left-1/2 h-1 bg-gradient-to-r from-purple-500 to-transparent rounded-full"
            style={{ transformOrigin: 'left center' }}
            animate={{
              width: ['0%', '100%', '0%'],
              opacity: [0, 1, 0],
            }}
            transition={{
              duration: 1.5,
              repeat: Infinity,
              ease: 'easeInOut',
            }}
          />
        </motion.div>
      )}

      {/* Outer ring - domain color */}
      <motion.div
        className={`absolute rounded-full opacity-20`}
        style={{
          backgroundColor: zone.color,
          width: size === 'lg' ? '96px' : size === 'md' ? '72px' : '56px',
          height: size === 'lg' ? '96px' : size === 'md' ? '72px' : '56px',
        }}
        animate={{
          scale: agent.state !== 'idle' ? [1, 1.15, 1] : [1, 1.05, 1],
        }}
        transition={{
          duration: agent.state === 'thinking' ? 1 : 3,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      {/* Main node */}
      <motion.button
        onClick={handleClick}
        className={`relative ${sizeClasses[size]} rounded-full cursor-pointer
          flex items-center justify-center
          border border-white/10 backdrop-blur-sm
          transition-all duration-300 ${getStateStyles()}`}
        style={{
          background: `linear-gradient(135deg, ${zone.color}40, ${zone.color}20)`,
        }}
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.95 }}
        animate={{
          boxShadow: isFocused
            ? `0 0 40px 15px ${zone.color}40`
            : `0 0 20px 5px ${zone.color}20`,
        }}
      >
        {/* Inner highlight */}
        <div className="absolute inset-1 rounded-full bg-gradient-to-br from-white/10 to-transparent" />

        {/* Domain icon */}
        <DomainIcon className={`${iconSizes[size]} text-white relative z-10`} />

        {/* State indicator badge */}
        {agent.state !== 'idle' && (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute -bottom-1 -right-1 h-5 w-5 rounded-full 
              bg-slate-800 border border-slate-600
              flex items-center justify-center"
          >
            <StateIcon
              className={`h-3 w-3 text-white ${
                agent.state === 'thinking' ? 'animate-spin' : ''
              }`}
            />
          </motion.div>
        )}

        {/* Active work items badge */}
        {agent.activeWorkItems > 0 && (
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute -top-1 -right-1 h-5 w-5 rounded-full 
              text-white text-xs font-bold flex items-center justify-center
              border border-slate-700"
            style={{ backgroundColor: zone.color }}
          >
            {agent.activeWorkItems}
          </motion.div>
        )}
      </motion.button>

      {/* Details */}
      {showDetails && (
        <div className="text-center space-y-0.5">
          <h4 className="text-sm font-medium text-white">{zone.label}</h4>
          <div className="flex items-center justify-center gap-1 text-xs text-slate-400">
            <StateIcon
              className={`h-3 w-3 ${
                agent.state === 'thinking' ? 'animate-spin' : ''
              }`}
            />
            <span>{STATE_DESCRIPTIONS[agent.state]}</span>
          </div>
        </div>
      )}
    </div>
  );
}
