'use client';

import { useState } from 'react';
import { AppShell } from '@/shared/layouts/AppShell';
import { PromptEditor, PromptSuggestions, ContextPanel, ConfigurationPanel, LaunchDialog } from '@/features/missions/components';
import { promptSuggestions, mockProjectContext } from '@/features/missions/constants/mock';
import { ArrowLeft, Rocket } from 'lucide-react';
import Link from 'next/link';

export default function NewMissionPage() {
  const [prompt, setPrompt] = useState('');
  const [showLaunch, setShowLaunch] = useState(false);

  return (
    <AppShell>
      <div className="p-6 lg:p-8 max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Link href="/missions" className="p-1.5 rounded-[var(--radius-md)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-all">
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div>
              <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">New Mission</h1>
              <p className="text-xs text-[var(--color-text-secondary)]">Describe what you want the swarm to build</p>
            </div>
          </div>
          <button
            onClick={() => setShowLaunch(true)}
            disabled={!prompt.trim()}
            className="inline-flex items-center gap-2 h-9 px-4 rounded-[var(--radius-md)] bg-[var(--color-primary)] text-white text-sm font-medium hover:bg-[var(--color-primary-hover)] disabled:opacity-40 disabled:pointer-events-none transition-all"
          >
            <Rocket className="w-4 h-4" />
            Launch
            <kbd className="text-[10px] opacity-70 bg-white/20 px-1.5 py-0.5 rounded hidden sm:inline">Enter</kbd>
          </button>
        </div>

        {/* Three-panel layout */}
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr_240px] gap-6">
          {/* Left: Context */}
          <div className="hidden lg:block">
            <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4 sticky top-6">
              <ContextPanel data={mockProjectContext} />
            </div>
          </div>

          {/* Center: Composer */}
          <div className="flex flex-col gap-4">
            <PromptEditor value={prompt} onChange={setPrompt} />
            <PromptSuggestions suggestions={promptSuggestions} onSelect={setPrompt} />
          </div>

          {/* Right: Configuration */}
          <div className="hidden lg:block">
            <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4 sticky top-6">
              <ConfigurationPanel />
            </div>
          </div>
        </div>
      </div>

      <LaunchDialog open={showLaunch} onClose={() => setShowLaunch(false)} prompt={prompt} />
    </AppShell>
  );
}
