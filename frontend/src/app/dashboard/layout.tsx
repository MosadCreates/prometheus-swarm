"use client";

import { useAuth } from "@/components/AuthProvider";
import { AppShell } from "@/shared/layouts/AppShell";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[var(--color-bg)]">
        <span className="w-5 h-5 rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-primary)] animate-spin" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[var(--color-bg)]">
        <div className="bg-[var(--color-surface-elevated)] border border-[var(--color-border)] rounded-[var(--radius-lg)] p-8 text-center max-w-sm shadow-sm">
          <p className="text-sm text-[var(--color-text-muted)] mb-4">Please sign in to access the dashboard.</p>
          <a href="/login" className="btn-accent inline-block text-sm">Sign in</a>
        </div>
      </div>
    );
  }

  return (
    <AppShell>
      {children}
    </AppShell>
  );
}
