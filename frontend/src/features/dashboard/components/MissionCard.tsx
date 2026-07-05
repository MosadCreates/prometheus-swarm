'use client';

import Link from 'next/link';
import { cn } from '@/shared/utils/cn';
import { Badge } from '@/shared/ui';
import { ArrowRight } from 'lucide-react';

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
      className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-surface)] transition-colors group no-underline"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs text-[var(--color-text-primary)] truncate">{mission.name}</span>
          <Badge variant={mission.status as any} size="sm">{mission.status}</Badge>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono text-[var(--color-text-muted)]">
          <span>{mission.agents.length} agents</span>
          <span>·</span>
          <span>{mission.started}</span>
        </div>
      </div>
      <ArrowRight className="w-3 h-3 text-[var(--color-text-muted)] group-hover:text-[var(--color-accent)] transition-colors shrink-0" />
    </Link>
  );
}
