'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { AppShell } from '@/shared/layouts/AppShell';
import { MissionHeader } from '@/features/missions/components/mc/MissionHeader';
import { AgentCard } from '@/features/missions/components/mc/AgentCard';
import { ActivityItem } from '@/features/missions/components/mc/ActivityItem';
import { MissionTimeline } from '@/features/missions/components/mc/Timeline';
import { ResourceBar } from '@/features/missions/components/mc/ResourceBar';
import { ArtifactCard } from '@/features/missions/components/mc/ArtifactCard';
import { AgentDrawer } from '@/features/missions/components/mc/AgentDrawer';
import { mockMission, mockAgents, mockEvents, mockTimeline, mockArtifacts, mockResources } from '@/features/missions/constants/mock-mission';

type Agent = typeof mockAgents[0];

export default function MissionControlPage() {
  const params = useParams();
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [filter, setFilter] = useState<string>('all');
  const missionName = params?.missionId === 'demo' ? 'Demo Mission' : `Mission ${params?.missionId}`;
  const mission = { ...mockMission, name: missionName };

  const filteredEvents = filter === 'all' ? mockEvents : mockEvents.filter(e => e.agent.toLowerCase() === filter);
  const agents = mockAgents;

  return (
    <AppShell>
      <div className="flex flex-col h-[calc(100vh-var(--header-height))]">
        <MissionHeader
          name={mission.name}
          project={mission.project}
          status={mission.status}
          progress={mission.progress}
          runtime={mission.runtime}
          started={mission.started}
          eta={mission.eta}
        />

        <MissionTimeline stages={mockTimeline} />

        {/* Main 3-panel body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left — Agent Fleet */}
          <aside className="w-60 shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] overflow-y-auto">
            <div className="p-3 border-b border-[var(--color-border)]">
              <h2 className="text-xs font-semibold text-[var(--color-text-primary)] uppercase tracking-wider">Agent Fleet</h2>
            </div>
            <div className="p-2 space-y-0.5">
              {agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onSelect={() => setSelectedAgent(agent)}
                />
              ))}
            </div>
          </aside>

          {/* Center — Activity Feed */}
          <main className="flex-1 flex flex-col overflow-hidden bg-[var(--color-bg)]">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--color-border)] bg-[var(--color-surface)] shrink-0">
              <h2 className="text-xs font-semibold text-[var(--color-text-primary)] uppercase tracking-wider">Activity</h2>
              <div className="flex items-center gap-1 ml-auto">
                {['all', ...new Set(agents.map(a => a.name.toLowerCase()))].map((a) => (
                  <button
                    key={a}
                    onClick={() => setFilter(a)}
                    className={`text-[11px] px-2 py-0.5 rounded-[var(--radius-sm)] transition-colors ${
                      filter === a
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)]'
                    }`}
                  >
                    {a === 'all' ? 'All' : a.charAt(0).toUpperCase() + a.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto divide-y divide-[var(--color-border-light)]">
              {filteredEvents.map((event) => (
                <ActivityItem key={event.id} event={event} />
              ))}
            </div>
          </main>

          {/* Right — Details Panel */}
          <aside className="w-72 shrink-0 border-l border-[var(--color-border)] bg-[var(--color-surface)] overflow-y-auto">
            {/* Summary */}
            <div className="p-4 border-b border-[var(--color-border)]">
              <h3 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Mission Summary</h3>
              <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed mb-3">{mission.goal}</p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[var(--color-text-muted)]">Priority</span>
                <span className="text-xs font-medium text-[var(--color-text-primary)]">{mission.priority}</span>
              </div>
            </div>

            {/* Resources */}
            <div className="px-4 py-3 border-b border-[var(--color-border)]">
              <h3 className="text-xs font-semibold text-[var(--color-text-primary)] mb-3 uppercase tracking-wider">Resources</h3>
              <div className="space-y-2">
                <ResourceBar label="CPU" value={mockResources.cpu} color="var(--color-accent)" />
                <ResourceBar label="GPU" value={mockResources.gpu} color="var(--color-warning)" />
                <ResourceBar label="Memory" value={mockResources.memory} color="var(--color-cyan)" />
                <ResourceBar label="Storage" value={mockResources.storage} color="var(--color-text-muted)" />
              </div>
            </div>

            {/* Artifacts */}
            <div className="px-4 py-3 border-b border-[var(--color-border)]">
              <h3 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Artifacts</h3>
              <div className="space-y-0.5">
                {mockArtifacts.map((a) => (
                  <ArtifactCard key={a.name} artifact={a} />
                ))}
              </div>
            </div>

            {/* Warnings */}
            <div className="px-4 py-3">
              <h3 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Warnings</h3>
              <div className="bg-[var(--color-warning)]/5 border border-[var(--color-warning)]/20 rounded-[var(--radius-md)] p-2.5">
                <p className="text-[11px] text-[var(--color-warning)]">Validation pending — results expected in ~5 min</p>
              </div>
            </div>
          </aside>
        </div>
      </div>

      <AgentDrawer agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </AppShell>
  );
}
