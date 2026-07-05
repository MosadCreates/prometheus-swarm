'use client';

import { MetricCard, QuickActions, ProjectCard, MissionCard, ActivityFeed, ResourceCard } from '@/features/dashboard/components';
import { mockMetrics, mockQuickActions, mockProjects, mockMissions, mockActivity, mockResources } from '@/features/dashboard/constants/mock';

export default function DashboardPage() {
  return (
    <div className="p-6 lg:p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">Workspace</h1>
          <p className="text-sm text-[var(--color-text-secondary)] mt-0.5">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <a href="/missions" className="inline-flex items-center gap-2 h-9 px-4 rounded-[var(--radius-md)] bg-[var(--color-primary)] text-white text-sm font-medium hover:bg-[var(--color-primary-hover)] transition-colors no-underline">
          <span>New Mission</span>
          <kbd className="text-[10px] opacity-70 bg-white/20 px-1.5 py-0.5 rounded">N</kbd>
        </a>
      </div>

      {/* Workspace Summary */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {mockMetrics.map((metric, i) => (
            <MetricCard key={metric.label} {...metric} index={i} />
          ))}
        </div>
      </section>

      {/* Quick Actions */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Quick Actions</h2>
        <QuickActions actions={mockQuickActions} />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Active Missions */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Active Missions</h2>
          <div className="flex flex-col gap-2">
            {mockMissions.slice(0, 3).map((m) => (
              <MissionCard key={m.id} mission={m} />
            ))}
          </div>
        </section>

        {/* Recent Activity */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Recent Activity</h2>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4">
            <ActivityFeed items={mockActivity} />
          </div>
        </section>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Projects */}
        <section className="lg:col-span-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Recent Projects</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {mockProjects.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </section>

        {/* Pinned Resources */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Pinned</h2>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-3">
            {mockResources.map((r) => (
              <ResourceCard key={r.id} resource={r} />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
