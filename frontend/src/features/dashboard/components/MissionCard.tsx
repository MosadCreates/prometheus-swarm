'use client';

import Link from 'next/link';
import { cn } from '@/shared/utils/cn';
import { Badge } from '@/shared/ui';
import { ArrowRight } from 'lucide-react';
import { missionStatusStyles } from '../constants/mock';

interface Mission {
  id: string;
  name: string;
  status: string;
  progress: number;
  agents: string[];
  started: string;
  eta: string;
}

export function MissionCard({ mission }: { mission: Mission }) {
  return (
    <Link
      href={`/missions/${mission.id}`}
      className="block rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4 hover:shadow-md hover:border-[var(--color-border)] transition-all group no-underline"
    >
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm font-medium text-[var(--color-text-primary)]">{mission.name}</span>
        <Badge variant={mission.status as any} size="sm">{mission.status}</Badge>
      </div>

      <div className="w-full h-1.5 rounded-full bg-[var(--color-border-light)] mb-3 overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            mission.status === 'completed' && 'bg-[var(--color-success)]',
            mission.status === 'running' && 'bg-[var(--color-primary)]',
            mission.status === 'failed' && 'bg-[var(--color-error)]',
            mission.status === 'queued' && 'bg-[var(--color-text-muted)]',
          )}
          style={{ width: `${mission.progress}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className="text-[var(--color-text-muted)]">{mission.agents.length} agents</span>
          <span className="text-[var(--color-text-muted)]">·</span>
          <span className="text-[var(--color-text-secondary)]">{mission.started}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[var(--color-text-muted)]">{mission.eta}</span>
          <ArrowRight className="w-3 h-3 text-[var(--color-text-muted)] group-hover:text-[var(--color-primary)] transition-colors" />
        </div>
      </div>
    </Link>
  );
}
