'use client';

import { cn } from '@/shared/utils/cn';
import { Check } from 'lucide-react';

interface Stage {
  label: string;
  completed: boolean;
  active?: boolean;
}

export function MissionTimeline({ stages }: { stages: Stage[] }) {
  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-3">
      <div className="flex items-center gap-0">
        {stages.map((stage, i) => (
          <div key={stage.label} className="flex-1 flex items-center">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  'w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-all',
                  stage.completed && 'bg-[var(--color-cyan)] text-white',
                  stage.active && 'bg-[var(--color-accent)] text-white ring-2 ring-[var(--color-accent)]/20',
                  !stage.completed && !stage.active && 'bg-[var(--color-border)] text-[var(--color-text-muted)]',
                )}
              >
                {stage.completed ? <Check className="w-3 h-3" /> : i + 1}
              </div>
              <span
                className={cn(
                  'text-xs whitespace-nowrap',
                  stage.completed && 'text-[var(--color-cyan)] font-medium',
                  stage.active && 'text-[var(--color-accent)] font-medium',
                  !stage.completed && !stage.active && 'text-[var(--color-text-muted)]',
                )}
              >
                {stage.label}
              </span>
            </div>
            {i < stages.length - 1 && (
              <div className={cn('flex-1 h-px mx-2', stage.completed ? 'bg-[var(--color-cyan)]' : 'bg-[var(--color-border)]')} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
