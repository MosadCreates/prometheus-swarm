'use client';

import { AppShell } from '@/shared/layouts/AppShell';
import { Brain } from 'lucide-react';
import { Button } from '@/shared/ui';

export default function ModelsPage() {
  return (
    <AppShell>
      <div className="p-8 max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--color-text-primary)]">Models</h1>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1">Browse and compare trained models</p>
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border)] p-16 text-center">
          <Brain className="w-10 h-10 text-[var(--color-text-muted)] mx-auto mb-4" />
          <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-1">No models yet</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">Models will appear here after training completes.</p>
        </div>
      </div>
    </AppShell>
  );
}
