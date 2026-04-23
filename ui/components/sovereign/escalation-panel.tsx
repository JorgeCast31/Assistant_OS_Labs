'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useSovereignStore } from '@/stores/sovereign-store';
import { AGENT_ZONES, EscalationRequest } from '@/lib/sovereign-types';
import {
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  ArrowRight,
  Shield,
} from 'lucide-react';

const priorityColors = {
  low: 'border-slate-500 bg-slate-500/10',
  medium: 'border-blue-500 bg-blue-500/10',
  high: 'border-amber-500 bg-amber-500/10',
  critical: 'border-red-500 bg-red-500/10',
};

const priorityBadgeColors = {
  low: 'bg-slate-500',
  medium: 'bg-blue-500',
  high: 'bg-amber-500',
  critical: 'bg-red-500',
};

interface EscalationCardProps {
  escalation: EscalationRequest;
  onApprove: () => void;
  onDeny: () => void;
}

function EscalationCard({ escalation, onApprove, onDeny }: EscalationCardProps) {
  const zone = AGENT_ZONES[escalation.fromAgent];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -20, scale: 0.95 }}
      className={`p-4 rounded-lg border ${priorityColors[escalation.priority]}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="h-8 w-8 rounded-full flex items-center justify-center"
            style={{ backgroundColor: `${zone.color}30` }}
          >
            <AlertTriangle className="h-4 w-4" style={{ color: zone.color }} />
          </div>
          <div>
            <h4 className="text-sm font-medium text-white">
              {zone.label} Escalation
            </h4>
            <p className="text-xs text-slate-400">
              {new Date(escalation.timestamp).toLocaleTimeString()}
            </p>
          </div>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium text-white ${
            priorityBadgeColors[escalation.priority]
          }`}
        >
          {escalation.priority}
        </span>
      </div>

      {/* Flow visualization */}
      <div className="flex items-center gap-2 mb-3 py-2 px-3 bg-slate-800/50 rounded-lg">
        <div
          className="h-6 w-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
          style={{ backgroundColor: zone.color }}
        >
          {escalation.fromAgent[0]}
        </div>
        <ArrowRight className="h-4 w-4 text-slate-500" />
        <div className="h-6 w-6 rounded-full bg-slate-600 flex items-center justify-center">
          <Shield className="h-3 w-3 text-white" />
        </div>
        <span className="text-xs text-slate-400 ml-2">
          Requesting MSO authority
        </span>
      </div>

      {/* Reason */}
      <div className="mb-3">
        <p className="text-xs text-slate-500 mb-1">Reason</p>
        <p className="text-sm text-slate-300">{escalation.reason}</p>
      </div>

      {/* Context */}
      <div className="mb-4">
        <p className="text-xs text-slate-500 mb-1">Context</p>
        <p className="text-xs text-slate-400 bg-slate-800/50 p-2 rounded">
          {escalation.context}
        </p>
      </div>

      {/* Required Authority */}
      <div className="mb-4 p-2 bg-purple-500/10 border border-purple-500/30 rounded">
        <p className="text-xs text-purple-400">
          Required: {escalation.requiredAuthority}
        </p>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onApprove}
          className="flex-1 flex items-center justify-center gap-2 py-2 px-4 
            bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium 
            rounded-lg transition-colors"
        >
          <CheckCircle className="h-4 w-4" />
          Approve
        </motion.button>
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onDeny}
          className="flex-1 flex items-center justify-center gap-2 py-2 px-4 
            bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium 
            rounded-lg transition-colors"
        >
          <XCircle className="h-4 w-4" />
          Deny
        </motion.button>
      </div>
    </motion.div>
  );
}

export function EscalationPanel() {
  const { mso, resolveEscalation, addMessage } = useSovereignStore();
  const escalations = mso.activeDecisions;

  const handleApprove = (escalation: EscalationRequest) => {
    resolveEscalation(escalation.id, 'approved');
    addMessage({
      from: 'MSO',
      content: `Approved escalation from ${escalation.fromAgent}: ${escalation.reason}`,
      type: 'decision',
      metadata: { decisionOutcome: 'approved', escalationId: escalation.id },
    });
  };

  const handleDeny = (escalation: EscalationRequest) => {
    resolveEscalation(escalation.id, 'denied');
    addMessage({
      from: 'MSO',
      content: `Denied escalation from ${escalation.fromAgent}: ${escalation.reason}`,
      type: 'decision',
      metadata: { decisionOutcome: 'denied', escalationId: escalation.id },
    });
  };

  if (escalations.length === 0) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 300 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 300 }}
      className="absolute top-4 right-4 w-80 max-h-[calc(100vh-8rem)] overflow-y-auto
        bg-slate-900/95 backdrop-blur-xl rounded-xl border border-slate-700/50
        shadow-2xl shadow-black/50"
    >
      {/* Header */}
      <div className="sticky top-0 bg-slate-900/95 backdrop-blur-xl p-4 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-full bg-amber-500/20 flex items-center justify-center">
            <Clock className="h-4 w-4 text-amber-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">
              Pending Decisions
            </h3>
            <p className="text-xs text-slate-400">
              {escalations.length} awaiting MSO review
            </p>
          </div>
        </div>
      </div>

      {/* Escalation cards */}
      <div className="p-4 space-y-4">
        <AnimatePresence mode="popLayout">
          {escalations.map((escalation) => (
            <EscalationCard
              key={escalation.id}
              escalation={escalation}
              onApprove={() => handleApprove(escalation)}
              onDeny={() => handleDeny(escalation)}
            />
          ))}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
