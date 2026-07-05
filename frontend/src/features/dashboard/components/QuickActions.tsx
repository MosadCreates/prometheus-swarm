'use client';

import Link from 'next/link';
import { Rocket, FolderKanban, Upload, Brain, GraduationCap, Globe, type LucideIcon } from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  Rocket, FolderKanban, Upload, Brain, GraduationCap, Globe,
};

interface Action {
  label: string;
  href: string;
  icon: string;
}

export function QuickActions({ actions }: { actions: Action[] }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      {actions.map((action) => {
        const Icon = iconMap[action.icon];
        return (
          <Link
            key={action.label}
            href={action.href}
            className="flex flex-col items-center gap-1.5 p-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] hover:border-[var(--color-primary)]/30 hover:shadow-sm transition-all text-center no-underline group"
          >
            {Icon && <Icon className="w-5 h-5 text-[var(--color-text-muted)] group-hover:text-[var(--color-primary)] transition-colors" />}
            <span className="text-[11px] font-medium text-[var(--color-text-secondary)] leading-tight">{action.label}</span>
          </Link>
        );
      })}
    </div>
  );
}
