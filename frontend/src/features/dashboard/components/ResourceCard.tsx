'use client';

import { BookOpen, Database, Brain, type LucideIcon } from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  doc: BookOpen,
  dataset: Database,
  model: Brain,
};

interface Resource {
  id: string;
  name: string;
  type: string;
}

export function ResourceCard({ resource }: { resource: Resource }) {
  const Icon = iconMap[resource.type] || BookOpen;
  return (
    <div className="flex items-center gap-2.5 px-4 py-3 hover:bg-[var(--color-surface)] transition-colors cursor-pointer">
      <Icon className="w-3.5 h-3.5 text-[var(--color-text-muted)] shrink-0" />
      <span className="text-xs text-[var(--color-text-primary)] truncate">{resource.name}</span>
    </div>
  );
}
