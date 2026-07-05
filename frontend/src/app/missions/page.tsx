'use client';

import { AppShell } from '@/shared/layouts/AppShell';
import { Rocket, Plus } from 'lucide-react';
import { Button } from '@/shared/ui';

export default function MissionsPage() {
  return (
    <AppShell>
      <div className="p-8 max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--color-text-primary)]">Missions</h1>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1">View and manage your swarm missions</p>
          </div>
          <a href="/missions/new">
            <Button size="sm">
              <Plus className="w-4 h-4" />
              New Mission
            </Button>
          </a>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border)] p-16 text-center">
          <Rocket className="w-10 h-10 text-[var(--color-text-muted)] mx-auto mb-4" />
          <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-1">No missions yet</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">Launch your first mission to see it here.</p>
          <Button size="sm">
            <Plus className="w-4 h-4" />
            New Mission
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
