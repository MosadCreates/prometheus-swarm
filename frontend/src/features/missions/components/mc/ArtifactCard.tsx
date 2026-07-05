'use client';

import { FileCode, FileJson, FileText, type LucideIcon } from 'lucide-react';

const iconMap: Record<string, LucideIcon> = {
  code: FileCode,
  json: FileJson,
  text: FileText,
};

interface Artifact {
  name: string;
  type: string;
  size: string;
}

export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const Icon = iconMap[artifact.type] || FileText;
  return (
    <div className="flex items-center gap-2.5 p-2 rounded-[var(--radius-md)] hover:bg-[var(--color-border-light)] transition-colors cursor-pointer">
      <Icon className="w-4 h-4 text-[var(--color-text-muted)] shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-[var(--color-text-primary)] truncate">{artifact.name}</p>
        <p className="text-[10px] text-[var(--color-text-muted)]">{artifact.size}</p>
      </div>
    </div>
  );
}
