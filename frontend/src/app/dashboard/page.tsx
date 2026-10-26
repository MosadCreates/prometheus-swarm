'use client';

import { useEffect, useMemo, useState } from 'react';
import { MetricCard, QuickActions, ProjectCard, MissionCard, ActivityFeed, ResourceCard } from '@/features/dashboard/components';
import { mockQuickActions, mockProjects, mockMissions, mockActivity, mockResources } from '@/features/dashboard/constants/mock';

interface Stats {
  active: number;
  queued: number;
  completed: number;
  failed: number;
  total: number;
  trained_models: number;
  recent_missions: {
    id: string;
    name: string;
    status: string;
    progress: number;
    agents: string[];
    started: string;
    eta: string;
  }[];
}

interface FeedEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

function agentLabel(stream: string): string {
  if (stream.includes('scout')) return 'Scout';
  if (stream.includes('forge')) return 'Forge';
  if (stream.includes('furnace')) return 'Furnace';
  if (stream.includes('dissect')) return 'Dissect';
  if (stream.includes('arbiter')) return 'Arbiter';
  if (stream.includes('harbor')) return 'Harbor';
  return 'Orch';
}

function toActivity(evt: FeedEvent) {
  const data = evt.data || {};
  const stream = evt.stream || '';
  let type = 'mission';
  if (stream.includes('harbor')) type = 'deployment';
  else if (stream.includes('forge') || stream.includes('furnace') || stream.includes('dissect')) type = 'model';

  const preview = data.exception_type || data.reason || data.message || data.event_type || 'event';
  const title = `${agentLabel(stream)} · ${data.event_type || preview}`;
  const time = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '';
  return { id: evt.id, type, title, description: preview, time };
}

function shortStarted(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [activity, setActivity] = useState<ReturnType<typeof toActivity>[]>([]);
  const [connected, setConnected] = useState(false);

  // Live stats + recent missions.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        if (!cancelled) setStats(data);
      } catch {
        // backend unreachable — fall back to mock below
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Live activity feed (SSE).
  useEffect(() => {
    const evtSource = new EventSource('/api/feed');
    evtSource.onopen = () => setConnected(true);
    evtSource.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed.status === 'connected' || parsed.error) return;
        setActivity((prev) => [toActivity(parsed), ...prev].slice(0, 12));
      } catch {}
    };
    evtSource.onerror = () => setConnected(false);
    return () => evtSource.close();
  }, []);

  const metrics = useMemo(() => {
    if (!stats) {
      return [
        { label: 'Active Missions', value: '—', change: undefined as string | undefined },
        { label: 'Queued', value: '—', change: undefined as string | undefined },
        { label: 'Completed', value: '—', change: undefined as string | undefined },
        { label: 'Trained Models', value: '—', change: undefined as string | undefined },
      ];
    }
    return [
      { label: 'Active Missions', value: stats.active, change: stats.active > 0 ? `+${stats.active}` : undefined },
      { label: 'Queued', value: stats.queued, change: undefined },
      { label: 'Completed', value: stats.completed, change: undefined },
      { label: 'Trained Models', value: stats.trained_models, change: undefined },
    ];
  }, [stats]);

  const missions = stats?.recent_missions?.length
    ? stats.recent_missions.map((m) => ({ ...m, started: shortStarted(m.started) }))
    : mockMissions;

  const activityItems = activity.length ? activity : mockActivity;

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
          {metrics.map((metric, i) => (
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
            {missions.slice(0, 3).map((m) => (
              <MissionCard key={m.id} mission={m} />
            ))}
          </div>
        </div>
        <div className="bg-[var(--color-bg)]">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Recent Activity</h2>
            {connected && <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-cyan)]" />}
          </div>
          <ActivityFeed items={activityItems} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
        <div className="lg:col-span-2 bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Recent Projects</h2>
            <span className="text-[9px] font-mono text-[var(--color-text-muted)]/60 uppercase tracking-wider">static</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-[var(--color-border)]">
            {mockProjects.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        </div>
        <div className="bg-[var(--color-bg)]">
          <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">Pinned</h2>
            <span className="text-[9px] font-mono text-[var(--color-text-muted)]/60 uppercase tracking-wider">static</span>
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
