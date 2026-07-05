'use client';

import { useState } from 'react';
import { cn } from '@/shared/utils/cn';
import { ChevronRight } from 'lucide-react';
import { agentStatusColor } from '../../constants/mock-mission';

interface Agent {
  id: string;
  name: string;
  role: string;
  status: string;
  task: string;
  progress: number;
  color: string;
}

export function AgentCard({ agent, onSelect }: { agent: Agent; onSelect: () => void }) {
  const color = agentStatusColor[agent.status] || 'var(--color-text-muted)';

  return (
    <button
      onClick={onSelect}
      className="w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-md)] hover:bg-[var(--color-border-light)] transition-colors text-left group"
    >
      <div className="w-7 h-7 rounded-[var(--radius-md)] flex items-center justify-center shrink-0 text-xs font-bold text-white" style={{ backgroundColor: agent.color }}>
        {agent.name[0]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-[var(--color-text-primary)]">{agent.name}</span>
          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[var(--color-text-muted)]">{agent.role}</span>
          <span className="text-[10px] text-[var(--color-text-muted)]">·</span>
          <span className="text-[11px] text-[var(--color-text-secondary)] truncate">{agent.task}</span>
        </div>
      </div>
      <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-muted)] group-hover:text-[var(--color-text-secondary)] transition-colors shrink-0" />
    </button>
  );
}
