"use client";

import { useEffect, useState } from "react";

export default function OrchestratorBanner() {
  const [alive, setAlive] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const r = await fetch("/api/health");
        const d = await r.json();
        if (!cancelled) setAlive(d.orchestrator === true);
      } catch {
        if (!cancelled) setAlive(false);
      }
    }
    check();
    const id = setInterval(check, 10000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (alive !== false) return null;

  return (
    <div className="bg-[var(--color-warning)]/10 border-b border-[var(--color-border)] px-6 py-2 text-xs text-[var(--color-warning)] flex items-center gap-2 fixed z-40" style={{ top: 'var(--header-height)', left: 0, right: 0 }}>
      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-warning)]" />
      <span className="font-semibold">Orchestrator not running</span>
      <span className="text-[var(--color-warning)]/50">&mdash;</span>
      <span className="text-[var(--color-warning)]/70">Run <code className="bg-[var(--color-warning)]/10 border border-[var(--color-border)] px-1.5 py-0.5 rounded text-[11px] font-mono">.\start.ps1</code> to start the agent pipeline</span>
    </div>
  );
}
