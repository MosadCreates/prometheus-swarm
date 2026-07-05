'use client';

import { useState } from 'react';
import { cn } from '@/shared/utils/cn';
import { ChevronDown, ChevronRight, Sparkles } from 'lucide-react';

interface Event {
  id: string;
  agent: string;
  action: string;
  status: string;
  time: string;
  detail: string;
}

const statusDots: Record<string, string> = {
  completed: 'bg-[var(--color-success)]',
  running: 'bg-[var(--color-primary)] animate-pulse',
  thinking: 'bg-[var(--color-warning)] animate-pulse',
};

export function ActivityItem({ event }: { event: Event }) {
  const [expanded, setExpanded] = useState(false);
  const dotColor = statusDots[event.status] || 'bg-[var(--color-text-muted)]';

  return (
    <div className="group">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-border-light)] transition-colors text-left"
      >
        <span className={cn('w-2 h-2 rounded-full shrink-0', dotColor)} />
        <span className="w-16 text-[11px] text-[var(--color-text-muted)] shrink-0">{event.time}</span>
        <span className="text-xs font-medium text-[var(--color-agent-scout)] w-14 shrink-0">{event.agent}</span>
        <span className="text-sm text-[var(--color-text-primary)] flex-1 truncate">{event.action}</span>
        {expanded ? <ChevronDown className="w-3.5 h-3.5 text-[var(--color-text-muted)]" /> : <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-muted)]" />}
      </button>
      {expanded && (
        <div className="px-4 pb-3 ml-7">
          <div className="rounded-[var(--radius-md)] bg-[var(--color-surface)] border border-[var(--color-border)] p-3 text-xs text-[var(--color-text-secondary)] leading-relaxed">
            {event.detail}
          </div>
        </div>
      )}
    </div>
  );
}
