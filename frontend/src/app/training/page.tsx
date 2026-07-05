'use client';

import { AppShell } from '@/shared/layouts/AppShell';
import { GraduationCap } from 'lucide-react';

export default function TrainingPage() {
  return (
    <AppShell>
      <div className="p-8 max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--color-text-primary)]">Training</h1>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1">Monitor active and completed training runs</p>
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border)] p-16 text-center">
          <GraduationCap className="w-10 h-10 text-[var(--color-text-muted)] mx-auto mb-4" />
          <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-1">No training runs</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">Training activity will appear here.</p>
        </div>
      </div>
    </AppShell>
  );
}
