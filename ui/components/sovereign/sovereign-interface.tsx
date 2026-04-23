'use client';

import { useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { WorldView } from './world-view';
import { EscalationPanel } from './escalation-panel';
import { InteractionPanel } from './interaction-panel';
import { SovereignToolbar } from './sovereign-toolbar';
import { useSovereignStore } from '@/stores/sovereign-store';

export function SovereignInterface() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const { focusedEntity } = useSovereignStore();

  // Auto-open chat when entity is focused
  const handleEntityFocus = () => {
    if (focusedEntity) {
      setIsChatOpen(true);
    }
  };

  return (
    <div className="relative w-full h-screen bg-slate-950 overflow-hidden">
      {/* Toolbar */}
      <SovereignToolbar
        onToggleChat={() => setIsChatOpen(!isChatOpen)}
        isChatOpen={isChatOpen}
      />

      {/* Main world view */}
      <WorldView />

      {/* Escalation panel (slides in from right when there are pending decisions) */}
      <AnimatePresence>
        <EscalationPanel />
      </AnimatePresence>

      {/* Interaction/chat panel */}
      <InteractionPanel
        isOpen={isChatOpen}
        onClose={() => setIsChatOpen(false)}
      />

      {/* Focus indicator overlay */}
      <AnimatePresence>
        {focusedEntity && (
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `radial-gradient(circle at center, transparent 30%, rgba(0,0,0,0.3) 100%)`,
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
