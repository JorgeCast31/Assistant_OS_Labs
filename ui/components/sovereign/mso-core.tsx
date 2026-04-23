'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import { EntityState, STATE_DESCRIPTIONS } from '@/lib/sovereign-types';
import { Shield, Activity, AlertTriangle, CheckCircle, Loader2, Clock } from 'lucide-react';

const stateColors: Record<EntityState, string> = {
  idle: 'from-slate-600 to-slate-700',
  thinking: 'from-blue-500 to-indigo-600',
  executing: 'from-emerald-500 to-teal-600',
  blocked: 'from-amber-500 to-orange-600',
  escalating: 'from-purple-500 to-violet-600',
  waiting: 'from-cyan-500 to-blue-600',
};

const stateGlowColors: Record<EntityState, string> = {
  idle: 'shadow-slate-500/20',
  thinking: 'shadow-blue-500/40',
  executing: 'shadow-emerald-500/40',
  blocked: 'shadow-amber-500/40',
  escalating: 'shadow-purple-500/40',
  waiting: 'shadow-cyan-500/40',
};

const StateIcon = ({ state }: { state: EntityState }) => {
  const iconClass = 'h-5 w-5';
  switch (state) {
    case 'idle':
      return <Shield className={iconClass} />;
    case 'thinking':
      return <Loader2 className={`${iconClass} animate-spin`} />;
    case 'executing':
      return <Activity className={iconClass} />;
    case 'blocked':
      return <AlertTriangle className={iconClass} />;
    case 'escalating':
      return <AlertTriangle className={iconClass} />;
    case 'waiting':
      return <Clock className={iconClass} />;
    default:
      return <CheckCircle className={iconClass} />;
  }
};

interface MSOCoreProps {
  onClick?: () => void;
  size?: 'sm' | 'md' | 'lg';
  showDetails?: boolean;
}

export function MSOCore({ onClick, size = 'lg', showDetails = true }: MSOCoreProps) {
  const { mso, focusEntity, focusedEntity } = useSovereignStore();
  const isFocused = focusedEntity === 'MSO';

  const sizeClasses = {
    sm: 'h-16 w-16',
    md: 'h-24 w-24',
    lg: 'h-32 w-32',
  };

  const ringSize = {
    sm: 'h-20 w-20',
    md: 'h-28 w-28',
    lg: 'h-40 w-40',
  };

  const outerRingSize = {
    sm: 'h-24 w-24',
    md: 'h-36 w-36',
    lg: 'h-48 w-48',
  };

  const handleClick = () => {
    if (onClick) {
      onClick();
    } else {
      focusEntity(isFocused ? null : 'MSO');
    }
  };

  return (
    <div className="relative flex flex-col items-center gap-4">
      {/* Outer pulsing ring - authority indicator */}
      <motion.div
        className={`absolute ${outerRingSize[size]} rounded-full border border-slate-600/30`}
        animate={{
          scale: mso.state === 'idle' ? [1, 1.05, 1] : [1, 1.1, 1],
          opacity: mso.state === 'idle' ? [0.3, 0.5, 0.3] : [0.5, 0.8, 0.5],
        }}
        transition={{
          duration: mso.state === 'idle' ? 4 : 2,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      {/* Middle ring - state indicator */}
      <motion.div
        className={`absolute ${ringSize[size]} rounded-full bg-gradient-to-br ${stateColors[mso.state]} opacity-20`}
        animate={{
          scale: [1, 1.08, 1],
          rotate: [0, 180, 360],
        }}
        transition={{
          duration: mso.state === 'thinking' ? 2 : 8,
          repeat: Infinity,
          ease: 'linear',
        }}
      />

      {/* Core element */}
      <motion.button
        onClick={handleClick}
        className={`relative ${sizeClasses[size]} rounded-full bg-gradient-to-br ${stateColors[mso.state]} 
          shadow-2xl ${stateGlowColors[mso.state]} cursor-pointer
          flex items-center justify-center
          border-2 border-white/10
          transition-all duration-300`}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.98 }}
        animate={{
          boxShadow: isFocused
            ? '0 0 60px 20px rgba(100, 130, 255, 0.3)'
            : '0 0 30px 10px rgba(100, 130, 255, 0.1)',
        }}
      >
        {/* Inner glow */}
        <div className="absolute inset-2 rounded-full bg-gradient-to-br from-white/20 to-transparent" />
        
        {/* Center icon */}
        <div className="relative z-10 text-white">
          <Shield className={size === 'lg' ? 'h-12 w-12' : size === 'md' ? 'h-8 w-8' : 'h-6 w-6'} />
        </div>

        {/* Active decisions badge */}
        <AnimatePresence>
          {mso.activeDecisions.length > 0 && (
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              className="absolute -top-1 -right-1 h-6 w-6 rounded-full bg-amber-500 
                text-white text-xs font-bold flex items-center justify-center
                border-2 border-slate-900"
            >
              {mso.activeDecisions.length}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.button>

      {/* Details panel */}
      {showDetails && (
        <div className="text-center space-y-1">
          <h3 className="text-lg font-semibold text-white">MSO</h3>
          <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
            <StateIcon state={mso.state} />
            <span>{STATE_DESCRIPTIONS[mso.state]}</span>
          </div>
          {mso.activeDecisions.length > 0 && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-xs text-amber-400"
            >
              {mso.activeDecisions.length} pending decision
              {mso.activeDecisions.length > 1 ? 's' : ''}
            </motion.p>
          )}
        </div>
      )}
    </div>
  );
}
