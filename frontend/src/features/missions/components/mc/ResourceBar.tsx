'use client';

import { cn } from '@/shared/utils/cn';

export function ResourceBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-[var(--color-text-muted)]">{label}</span>
        <span className="text-xs text-[var(--color-text-secondary)]">{value}%</span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-[var(--color-border-light)] overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${value}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}
