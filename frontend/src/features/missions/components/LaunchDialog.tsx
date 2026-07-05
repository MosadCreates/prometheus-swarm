'use client';

import { Dialog } from '@/shared/ui';
import { Rocket, CheckCircle } from 'lucide-react';
import { useState } from 'react';

interface LaunchDialogProps {
  open: boolean;
  onClose: () => void;
  prompt: string;
}

export function LaunchDialog({ open, onClose, prompt }: LaunchDialogProps) {
  const [launched, setLaunched] = useState(false);

  const handleLaunch = () => {
    setLaunched(true);
  };

  const handleClose = () => {
    setLaunched(false);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} title={launched ? 'Mission Created' : 'Launch Mission'} className="max-w-md">
      {!launched ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-[var(--color-text-secondary)]">
            Your mission will be processed by the swarm. You can monitor progress in Mission Control.
          </p>
          <div className="rounded-[var(--radius-md)] bg-[var(--color-surface)] border border-[var(--color-border)] p-3">
            <p className="text-xs text-[var(--color-text-secondary)] line-clamp-3">{prompt}</p>
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={handleClose} className="h-9 px-4 rounded-[var(--radius-md)] border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)] transition-colors">
              Cancel
            </button>
            <button onClick={handleLaunch} className="inline-flex items-center gap-2 h-9 px-4 rounded-[var(--radius-md)] bg-[var(--color-cyan)] text-white text-sm font-medium hover:bg-[var(--color-cyan-hover)] transition-colors">
              <Rocket className="w-4 h-4" />
              Launch Mission
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-4 py-4">
          <div className="w-12 h-12 rounded-full bg-[var(--color-cyan)]/10 flex items-center justify-center">
            <CheckCircle className="w-6 h-6 text-[var(--color-cyan)]" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-[var(--color-text-primary)]">Mission launched successfully</p>
            <p className="text-xs text-[var(--color-text-secondary)] mt-1">Redirecting to Mission Control...</p>
          </div>
        </div>
      )}
    </Dialog>
  );
}
