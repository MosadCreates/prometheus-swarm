'use client';

import { FolderKanban, FileText, Database, History, Brain, Plus } from 'lucide-react';

interface ContextData {
  name: string;
  files: string[];
  datasets: string[];
  previousMissions: string[];
  recentModels: string[];
}

export function ContextPanel({ data }: { data: ContextData }) {
  return (
    <div className="flex flex-col gap-5">
      {/* Current Project */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-1.5">
          <FolderKanban className="w-3 h-3" /> Project
        </h3>
        <div className="flex items-center gap-2 px-3 py-2 rounded-[var(--radius-md)] bg-[var(--color-surface)] border border-[var(--color-border)]">
          <div className="w-2 h-2 rounded-sm bg-[var(--color-primary)]" />
          <span className="text-sm text-[var(--color-text-primary)] font-medium">{data.name}</span>
        </div>
      </div>

      {/* Recent Files */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-1.5">
          <FileText className="w-3 h-3" /> Files
        </h3>
        <div className="flex flex-col gap-0.5">
          {data.files.map((f) => (
            <div key={f} className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-md)] text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)] transition-colors cursor-pointer">
              <FileText className="w-3.5 h-3.5 text-[var(--color-text-muted)]" />
              {f}
            </div>
          ))}
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-md)] text-xs text-[var(--color-primary)] hover:bg-[var(--color-primary)]/5 transition-colors">
            <Plus className="w-3.5 h-3.5" /> Add file
          </button>
        </div>
      </div>

      {/* Datasets */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-1.5">
          <Database className="w-3 h-3" /> Datasets
        </h3>
        <div className="flex flex-wrap gap-1.5">
          {data.datasets.map((d) => (
            <span key={d} className="text-xs px-2 py-1 rounded-[var(--radius-sm)] bg-[var(--color-primary)]/5 text-[var(--color-primary)] border border-[var(--color-primary)]/10">
              {d}
            </span>
          ))}
        </div>
      </div>

      {/* Previous Missions */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 flex items-center gap-1.5">
          <History className="w-3 h-3" /> Previous
        </h3>
        <div className="flex flex-col gap-0.5">
          {data.previousMissions.map((m) => (
            <div key={m} className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-md)] text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)] transition-colors cursor-pointer">
              <History className="w-3.5 h-3.5 text-[var(--color-text-muted)]" />
              {m}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
