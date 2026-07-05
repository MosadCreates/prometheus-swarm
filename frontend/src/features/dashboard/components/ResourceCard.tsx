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
    <div className="flex items-center gap-2.5 p-2.5 rounded-[var(--radius-md)] hover:bg-[var(--color-border-light)] transition-colors cursor-pointer">
      <Icon className="w-4 h-4 text-[var(--color-text-muted)] shrink-0" />
      <span className="text-sm text-[var(--color-text-primary)] truncate">{resource.name}</span>
    </div>
  );
}
