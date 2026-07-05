'use client';

import { X } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

interface Agent {
  id: string;
  name: string;
  role: string;
  status: string;
  task: string;
  progress: number;
  color: string;
}

const agentInfo: Record<string, { description: string; outputs: string[] }> = {
  scout: { description: 'Analyzes raw problem descriptions and datasets to produce a mission brief.', outputs: ['mission_brief.json', 'eda_report.json'] },
  forge: { description: 'Selects optimal model architecture and generates the training script.', outputs: ['training_script.py', 'search_space.json'] },
  furnace: { description: 'Runs the training process in an isolated Docker container.', outputs: ['best_model.ckpt', 'training_logs.json'] },
  dissect: { description: 'Diagnoses and patches training failures autonomously.', outputs: ['patch_log.json', 'fixed_script.py'] },
  arbiter: { description: 'Evaluates the trained model and decides pass/retry/escalate.', outputs: ['eval_report.json', 'metrics_summary.json'] },
  harbor: { description: 'Deploys the model as a live HTTPS endpoint.', outputs: ['endpoint_url', 'model.onnx', 'docker_compose.yml'] },
};

export function AgentDrawer({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  if (!agent) return null;
  const info = agentInfo[agent.id] || { description: '', outputs: [] };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-full max-w-sm bg-[var(--color-surface)] border-l border-[var(--color-border)] shadow-lg animate-slide-in-right overflow-y-auto">
        <div className="sticky top-0 bg-[var(--color-surface)] border-b border-[var(--color-border)] px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-[var(--radius-md)] flex items-center justify-center text-sm font-bold text-white" style={{ backgroundColor: agent.color }}>
              {agent.name[0]}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">{agent.name}</h3>
              <p className="text-xs text-[var(--color-text-muted)]">{agent.role}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-[var(--radius-sm)] hover:bg-[var(--color-border-light)]">
            <X className="w-4 h-4 text-[var(--color-text-muted)]" />
          </button>
        </div>
        <div className="p-5 space-y-5">
          <div>
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{info.description}</p>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Current Objective</h4>
            <p className="text-sm text-[var(--color-text-secondary)]">{agent.task}</p>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Progress</h4>
            <div className="w-full h-2 rounded-full bg-[var(--color-border-light)] overflow-hidden">
              <div className="h-full rounded-full transition-all" style={{ width: `${agent.progress}%`, backgroundColor: agent.color }} />
            </div>
            <p className="text-xs text-[var(--color-text-muted)] mt-1">{agent.progress}%</p>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Outputs</h4>
            <div className="space-y-1">
              {info.outputs.map((o) => (
                <div key={o} className="text-xs text-[var(--color-text-secondary)] py-1 px-2 rounded-[var(--radius-sm)] bg-[var(--color-border-light)]">{o}</div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-[var(--color-text-primary)] mb-2 uppercase tracking-wider">Recent Activity</h4>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-primary)]" />
                Initializing...
              </div>
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-success)]" />
                Ready
              </div>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slideInRight 0.2s ease-out;
        }
      `}</style>
    </div>
  );
}
