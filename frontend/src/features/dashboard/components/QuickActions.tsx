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
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
      {actions.map((action) => {
        const Icon = iconMap[action.icon];
        return (
          <Link
            key={action.label}
            href={action.href}
            className="flex flex-col items-center gap-1.5 p-3 bg-[var(--color-bg)] hover:bg-[var(--color-surface)] transition-colors no-underline group"
          >
            {Icon && <Icon className="w-4 h-4 text-[var(--color-text-muted)] group-hover:text-[var(--color-accent)] transition-colors" />}
            <span className="text-[10px] font-mono text-[var(--color-text-secondary)] leading-tight">{action.label}</span>
          </Link>
        );
      })}
    </div>
  );
}
