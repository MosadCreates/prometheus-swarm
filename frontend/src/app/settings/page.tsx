'use client';

import { AppShell } from '@/shared/layouts/AppShell';
import { Settings, User, Bell, Palette, Key, Shield } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

const sections = [
  { icon: User, label: 'Account', active: true },
  { icon: Bell, label: 'Notifications', active: false },
  { icon: Palette, label: 'Theme', active: false },
  { icon: Key, label: 'API Keys', active: false },
  { icon: Shield, label: 'Security', active: false },
];

export default function SettingsPage() {
  return (
    <AppShell>
      <div className="p-8 max-w-4xl mx-auto">
        <h1 className="text-2xl font-semibold text-[var(--color-text-primary)] mb-6">Settings</h1>
        <div className="flex gap-8">
          <nav className="w-48 shrink-0 flex flex-col gap-0.5">
            {sections.map((s) => (
              <button
                key={s.label}
                className={cn(
                  'flex items-center gap-2.5 px-3 py-2 rounded-[var(--radius-md)] text-sm transition-all text-left',
                  s.active
                    ? 'bg-[var(--color-accent)]/10 text-[var(--color-accent)] font-medium'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)]',
                )}
              >
                <s.icon className="w-4 h-4" />
                {s.label}
              </button>
            ))}
          </nav>
          <div className="flex-1">
            <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] p-6">
              <h2 className="text-lg font-medium text-[var(--color-text-primary)] mb-4">Account</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">Account settings will be available soon.</p>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
