'use client';

import { MetricCard, QuickActions, ProjectCard, MissionCard, ActivityFeed, ResourceCard } from '@/features/dashboard/components';
import { mockMetrics, mockQuickActions, mockProjects, mockMissions, mockActivity, mockResources } from '@/features/dashboard/constants/mock';

export default function DashboardPage() {
  return (
    <div className="p-6 lg:p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Workspace</h1>
          <p className="text-[10px] font-mono text-[var(--color-text-muted)] mt-0.5">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <a href="/submit" className="inline-flex items-center gap-2 h-8 px-3 rounded-[var(--radius-sm)] bg-[var(--color-accent)] text-white text-[11px] font-mono font-medium hover:bg-[var(--color-accent-hover)] transition-colors no-underline">
          New Problem
        </a>
      </div>

      <section className="mb-6">
        <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-3">Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-[var(--color-border)]">
          {mockMetrics.map((metric, i) => (
            <MetricCard key={metric.label} {...metric} index={i} />
          ))}
        </div>
      </section>

      <section className="mb-6">
        <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-3">Quick Actions</h2>
        <QuickActions actions={mockQuickActions} />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-[var(--color-border)] mb-6 border border-[var(--color-border)]">
        <div className="bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Active Missions</h2>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {mockMissions.slice(0, 3).map((m) => (
              <MissionCard key={m.id} mission={m} />
            ))}
          </div>
        </div>
        <div className="bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Recent Activity</h2>
          </div>
          <ActivityFeed items={mockActivity} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
        <div className="lg:col-span-2 bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Recent Projects</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-[var(--color-border)]">
            {mockProjects.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </div>
        <div className="bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Pinned</h2>
          </div>
          <div className="divide-y divide-[var(--color-border)]">
            {mockResources.map((r) => (
              <ResourceCard key={r.id} resource={r} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
