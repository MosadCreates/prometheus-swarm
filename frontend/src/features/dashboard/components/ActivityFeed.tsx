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
    <div className="flex flex-col">
      {items.map((item, i) => {
        const Icon = iconMap[item.type] || Rocket;
        const color = colorMap[item.type] || 'var(--color-text-muted)';
        return (
          <div key={item.id} className="flex gap-3 py-2.5 border-b border-[var(--color-border-light)] last:border-0">
            <div className="w-7 h-7 rounded-[var(--radius-md)] flex items-center justify-center shrink-0" style={{ backgroundColor: color + '15' }}>
              <Icon className="w-3.5 h-3.5" style={{ color }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-[var(--color-text-primary)] truncate">{item.title}</p>
              <p className="text-xs text-[var(--color-text-secondary)] truncate">{item.description}</p>
            </div>
            <span className="text-[11px] text-[var(--color-text-muted)] shrink-0">{item.time}</span>
          </div>
        );
      })}
    </div>
  );
}
