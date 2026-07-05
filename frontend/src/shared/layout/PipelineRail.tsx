'use client';

import { cn } from '@/shared/utils/cn';
import { Radar, Hammer, Flame, Search, Scale, Anchor, Check } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface Stage {
  id: string;
  label: string;
}

export interface PipelineState {
  completed: string[];
  active: string | null;
}

const stages: Stage[] = [
  { id: 'scout', label: 'Scout' },
  { id: 'forge', label: 'Forge' },
  { id: 'furnace', label: 'Furnace' },
  { id: 'dissect', label: 'Dissect' },
  { id: 'arbiter', label: 'Arbiter' },
  { id: 'harbor', label: 'Harbor' },
];

const stageIcons: Record<string, LucideIcon> = {
  scout: Radar,
  forge: Hammer,
  furnace: Flame,
  dissect: Search,
  arbiter: Scale,
  harbor: Anchor,
};

const stageColors: Record<string, string> = {
  scout: 'var(--color-agent-scout)',
  forge: 'var(--color-agent-forge)',
  furnace: 'var(--color-agent-furnace)',
  dissect: 'var(--color-agent-dissect)',
  arbiter: 'var(--color-agent-arbiter)',
  harbor: 'var(--color-agent-harbor)',
};

interface PipelineRailProps {
  state?: PipelineState;
  orientation?: 'vertical' | 'horizontal';
  showLabels?: boolean;
  className?: string;
}

export function PipelineRail({ state, orientation = 'vertical', showLabels = true, className }: PipelineRailProps) {
  const completed = state?.completed ?? [];
  const active = state?.active ?? null;

  return (
    <div className={cn(
      'flex',
      orientation === 'vertical' ? 'flex-col items-start' : 'flex-row items-center w-full',
      className,
    )}>
      {stages.map((stage, i) => {
        const Icon = stageIcons[stage.id];
        const isCompleted = completed.includes(stage.id);
        const isActive = active === stage.id;
        const isPending = !isCompleted && !isActive;
        const color = stageColors[stage.id];
        const showConnector = i < stages.length - 1;

        return (
          <div key={stage.id} className={cn(
            'flex',
            orientation === 'vertical' ? 'flex-col items-start' : 'flex-col items-center',
          )}>
            <div className={cn(
              'flex items-center gap-3',
              orientation === 'horizontal' && 'flex-col gap-1',
            )}>
              {/* Stage icon */}
              <div className={cn(
                'relative flex items-center justify-center transition-all duration-[var(--duration-normal)]',
                orientation === 'vertical' ? 'w-8 h-8' : 'w-7 h-7',
              )}>
                <div className={cn(
                  'flex items-center justify-center rounded-[var(--radius-sm)] transition-all',
                  orientation === 'vertical' ? 'w-8 h-8' : 'w-7 h-7',
                  isActive && 'glow-accent',
                )}>
                  {isCompleted ? (
                    <div className="flex items-center justify-center w-full h-full rounded-[var(--radius-sm)]" style={{ backgroundColor: color }}>
                      <Check className={cn('text-[var(--color-bg)]', orientation === 'vertical' ? 'w-4 h-4' : 'w-3.5 h-3.5')} />
                    </div>
                  ) : (
                    <div className={cn(
                      'flex items-center justify-center w-full h-full rounded-[var(--radius-sm)] border',
                      isActive
                        ? 'bg-[var(--color-accent)] border-[var(--color-accent)] text-white'
                        : 'bg-transparent border-[var(--color-border)] text-[var(--color-text-muted)]',
                    )}>
                      {Icon && <Icon className={orientation === 'vertical' ? 'w-4 h-4' : 'w-3.5 h-3.5'} />}
                    </div>
                  )}
                </div>
                {/* Traveling pulse for active stage */}
                {isActive && (
                  <span className="absolute inset-0 rounded-[var(--radius-sm)] animate-pulse-travel bg-[var(--color-accent)]/20" />
                )}
              </div>

              {/* Label */}
              {showLabels && (
                <span className={cn(
                  'font-mono text-[11px] font-medium transition-colors leading-none',
                  isCompleted && 'text-[var(--color-text-primary)]',
                  isActive && 'text-[var(--color-accent)]',
                  isPending && 'text-[var(--color-text-muted)]',
                )}>
                  {stage.label}
                </span>
              )}
            </div>

            {/* Connector line */}
            {showConnector && (
              <div className={cn(
                'relative',
                orientation === 'vertical' ? 'ml-4 w-px h-6' : 'w-8 h-px',
              )}>
                <div className={cn(
                  'absolute inset-0',
                  orientation === 'vertical' ? 'left-0 top-0 w-px' : 'top-0 left-0 h-px',
                  isCompleted ? 'bg-[var(--color-text-muted)]' : 'bg-[var(--color-border)]',
                )} />
                {isActive && (
                  <div className={cn(
                    'absolute inset-0 bg-[var(--color-accent)] animate-pulse-travel',
                    orientation === 'vertical' ? 'left-0 top-0 w-px' : 'top-0 left-0 h-px',
                  )} />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
