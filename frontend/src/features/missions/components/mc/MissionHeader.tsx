'use client';

import { cn } from '@/shared/utils/cn';

interface MissionHeaderProps {
  name: string;
  project: string;
  status: string;
  progress: number;
  runtime: string;
  started: string;
  eta: string;
}

const statusStyles: Record<string, string> = {
  running: 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
  queued: 'bg-[var(--color-text-muted)]/10 text-[var(--color-text-muted)]',
  completed: 'bg-[var(--color-success)]/10 text-[var(--color-success)]',
  failed: 'bg-[var(--color-error)]/10 text-[var(--color-error)]',
};

export function MissionHeader({ name, project, status, progress, runtime, started, eta }: MissionHeaderProps) {
  return (
    <div className="border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-xs text-[var(--color-text-muted)]">{project}</span>
            <span className="text-[10px] text-[var(--color-text-muted)]">/</span>
            <h1 className="text-base font-semibold text-[var(--color-text-primary)]">{name}</h1>
          </div>
          <div className="flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
            <span>Started {started}</span>
            <span>·</span>
            <span>Runtime {runtime}</span>
            <span>·</span>
            <span>ETA {eta}</span>
          </div>
        </div>
        <span className={cn('text-xs font-medium px-2.5 py-1 rounded-[var(--radius-sm)]', statusStyles[status])}>{status}</span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-[var(--color-border-light)] overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            status === 'completed' && 'bg-[var(--color-success)]',
            status === 'running' && 'bg-[var(--color-primary)]',
            status === 'failed' && 'bg-[var(--color-error)]',
          )}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
