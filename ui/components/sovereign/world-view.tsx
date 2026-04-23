'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import { MSOCore } from './mso-core';
import { AgentZone } from './agent-zone';
import { AgentDomain } from '@/lib/sovereign-types';

export function WorldView() {
  const { focusedEntity, setViewMode, mso, agents } = useSovereignStore();

  // Draw connection lines from agents to MSO
  const renderConnections = () => {
    const domains: AgentDomain[] = ['CODE', 'WORK', 'FIN', 'HOST'];
    
    return domains.map((domain) => {
      const agent = agents[domain];
      const isEscalating = agent.state === 'escalating';
      const isExecuting = agent.state === 'executing';
      
      // Position offsets for connection lines
      const positions: Record<AgentDomain, { startX: string; startY: string }> = {
        CODE: { startX: '22%', startY: '21%' },
        WORK: { startX: '78%', startY: '21%' },
        FIN: { startX: '22%', startY: '79%' },
        HOST: { startX: '78%', startY: '79%' },
      };

      const pos = positions[domain];

      return (
        <svg
          key={domain}
          className="absolute inset-0 pointer-events-none"
          style={{ zIndex: 0 }}
        >
          <defs>
            <linearGradient id={`gradient-${domain}`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={isEscalating ? '#a855f7' : '#64748b'} stopOpacity="0.1" />
              <stop offset="50%" stopColor={isEscalating ? '#a855f7' : '#64748b'} stopOpacity={isEscalating ? 0.6 : 0.2} />
              <stop offset="100%" stopColor={isEscalating ? '#a855f7' : '#64748b'} stopOpacity="0.1" />
            </linearGradient>
          </defs>
          <motion.line
            x1={pos.startX}
            y1={pos.startY}
            x2="50%"
            y2="50%"
            stroke={`url(#gradient-${domain})`}
            strokeWidth={isEscalating ? 3 : 1}
            strokeDasharray={isEscalating ? '8,4' : '4,4'}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: 1,
              opacity: isEscalating ? 1 : 0.3,
              strokeDashoffset: isEscalating ? [0, -24] : 0,
            }}
            transition={{
              pathLength: { duration: 0.5 },
              strokeDashoffset: { duration: 1, repeat: Infinity, ease: 'linear' },
            }}
          />
          {/* Data flow particles for active connections */}
          {(isEscalating || isExecuting) && (
            <motion.circle
              r="4"
              fill={isEscalating ? '#a855f7' : '#10b981'}
              initial={{ opacity: 0 }}
              animate={{
                opacity: [0, 1, 0],
                cx: [pos.startX, '50%'],
                cy: [pos.startY, '50%'],
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                ease: 'easeInOut',
              }}
            />
          )}
        </svg>
      );
    });
  };

  return (
    <div className="relative w-full h-full bg-slate-950 overflow-hidden">
      {/* Background grid */}
      <div
        className="absolute inset-0 opacity-5"
        style={{
          backgroundImage: `
            linear-gradient(to right, #64748b 1px, transparent 1px),
            linear-gradient(to bottom, #64748b 1px, transparent 1px)
          `,
          backgroundSize: '40px 40px',
        }}
      />

      {/* Radial gradient from center */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(circle at center, rgba(100, 116, 139, 0.1) 0%, transparent 60%)',
        }}
      />

      {/* Connection lines */}
      {renderConnections()}

      {/* Agent zones - four corners */}
      <AgentZone domain="CODE" />
      <AgentZone domain="WORK" />
      <AgentZone domain="FIN" />
      <AgentZone domain="HOST" />

      {/* MSO Core - center */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <motion.div
          className="pointer-events-auto"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 200, damping: 20 }}
        >
          <MSOCore size="lg" showDetails={true} />
        </motion.div>
      </div>

      {/* System health indicator */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2">
        <div
          className={`h-2 w-2 rounded-full ${
            mso.systemHealth === 'optimal'
              ? 'bg-emerald-500'
              : mso.systemHealth === 'degraded'
              ? 'bg-amber-500'
              : 'bg-red-500'
          }`}
        />
        <span className="text-xs text-slate-500 uppercase tracking-wider">
          System {mso.systemHealth}
        </span>
      </div>

      {/* View mode indicator */}
      <AnimatePresence>
        {focusedEntity && (
          <motion.button
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            onClick={() => setViewMode('world')}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 
              px-4 py-2 rounded-full bg-slate-800/80 border border-slate-700
              text-sm text-slate-300 hover:bg-slate-700/80 transition-colors"
          >
            Return to World View
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
