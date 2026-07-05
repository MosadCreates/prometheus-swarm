'use client';

import { AppShell } from '@/shared/layouts/AppShell';
import { Database, Upload } from 'lucide-react';
import { Button } from '@/shared/ui';

export default function DatasetsPage() {
  return (
    <AppShell>
      <div className="p-8 max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--color-text-primary)]">Datasets</h1>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1">Upload and manage your datasets</p>
          </div>
          <Button size="sm">
            <Upload className="w-4 h-4" />
            Upload
          </Button>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border)] p-16 text-center">
          <Database className="w-10 h-10 text-[var(--color-text-muted)] mx-auto mb-4" />
          <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-1">No datasets yet</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">Upload a dataset to get started.</p>
          <Button size="sm">
            <Upload className="w-4 h-4" />
            Upload Dataset
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
