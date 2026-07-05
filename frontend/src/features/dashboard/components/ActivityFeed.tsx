'use client';

import { Rocket, Brain, Database, Globe, FolderKanban, type LucideIcon } from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  mission: Rocket,
  model: Brain,
  dataset: Database,
  deployment: Globe,
  project: FolderKanban,
};

const colorMap: Record<string, string> = {
  mission: 'var(--color-agent-scout)',
  model: 'var(--color-agent-forge)',
  dataset: 'var(--color-agent-dissect)',
  deployment: 'var(--color-agent-harbor)',
  project: 'var(--color-agent-arbiter)',
};

interface Activity {
  id: string;
  type: string;
  title: string;
  description: string;
  time: string;
}

export function ActivityFeed({ items }: { items: Activity[] }) {
  return (
    <div className="divide-y divide-[var(--color-border)]">
      {items.map((item, i) => {
        const Icon = iconMap[item.type] || Rocket;
        const color = colorMap[item.type] || 'var(--color-text-muted)';
        return (
          <div key={item.id} className="flex gap-3 px-4 py-3 hover:bg-[var(--color-surface)] transition-colors">
            <Icon className="w-3.5 h-3.5 shrink-0 mt-0.5" style={{ color }} />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-[var(--color-text-primary)] truncate">{item.title}</p>
              <p className="text-[10px] font-mono text-[var(--color-text-secondary)] truncate">{item.description}</p>
            </div>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] shrink-0">{item.time}</span>
          </div>
        );
      })}
    </div>
  );
}
