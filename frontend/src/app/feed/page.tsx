"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/shared/utils/cn";

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

const PIPELINE_COLORS: Record<string, string> = {
  scout_output: "#38bdf8",
  forge_output: "#6366f1",
  furnace_feed: "#ff6b35",
  furnace_output: "#ff6b35",
  furnace_crash: "#e5484d",
  dissect_output: "#22c55e",
  arbiter_output: "#e8a33d",
  harbor_output: "#e85b5b",
  orchestrator_output: "#5a636e",
};

function agentColor(stream: string): string {
  for (const [key, color] of Object.entries(PIPELINE_COLORS)) {
    if (stream.includes(key)) return color;
  }
  return "#5a636e";
}

function agentLabel(stream: string): string {
  if (stream.includes("scout")) return "Scout";
  if (stream.includes("forge")) return "Forge";
  if (stream.includes("furnace_crash")) return "Furnace";
  if (stream.includes("furnace")) return "Furnace";
  if (stream.includes("dissect")) return "Dissect";
  if (stream.includes("arbiter")) return "Arbiter";
  if (stream.includes("harbor")) return "Harbor";
  return "Orch";
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null;
  const w = 48, h = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (w - 2) + 1;
    const y = h - 2 - ((v - min) / range) * (h - 4);
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="shrink-0" viewBox={`0 0 ${w} ${h}`}>
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

export default function FeedPage() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eventsToday, setEventsToday] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const evtSource = new EventSource("/api/feed");

    evtSource.onopen = () => setConnected(true);

    evtSource.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed.status === "connected") {
          setConnected(true);
          return;
        }
        if (parsed.error) {
          setError(parsed.error);
          return;
        }
        setEvents((prev) => {
          const next = [parsed, ...prev].slice(0, 200);
          return next;
        });
        setEventsToday((prev) => prev + 1);
      } catch {}
    };

    evtSource.onerror = () => {
      setConnected(false);
      setError("Connection lost. Retrying...");
    };

    return () => evtSource.close();
  }, []);

  // Build grouped events: add `sameAgent` flag when consecutive events match agent
  const grouped = events.map((evt, i) => {
    const prev = events[i - 1];
    const sameAgent = prev ? agentLabel(prev.stream) === agentLabel(evt.stream) : false;
    return { ...evt, sameAgent };
  });

  return (
    <div className="h-full flex flex-col bg-[var(--color-bg)]">
      {/* Sticky header */}
      <div className="sticky top-0 z-10 flex items-center gap-4 px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg)]/90 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          <span className={cn(
            "w-2 h-2 rounded-full",
            connected ? "bg-[var(--color-cyan)]" : "bg-[var(--color-alert)]",
          )} />
          <span className={`w-2 h-2 rounded-full absolute animate-ping ${connected ? "bg-[var(--color-cyan)]/40" : "bg-[var(--color-alert)]/40"}`} />
        </div>
        <span className="text-xs font-mono text-[var(--color-text-secondary)]">
          {eventsToday} events today
        </span>
        {!connected && (
          <span className="text-xs text-[var(--color-alert)]">Disconnected</span>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-6 mt-3 px-3 py-2 border border-[var(--color-alert)]/30 bg-[var(--color-alert)]/5 text-xs text-[var(--color-alert)]">
          {error}
        </div>
      )}

      {/* Empty state */}
      {events.length === 0 && !error && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs text-[var(--color-text-muted)] font-mono">awaiting signal...</span>
        </div>
      )}

      {/* Instrument log */}
      {events.length > 0 && (
        <div className="flex-1 overflow-y-auto px-6 py-3">
          <div className="flex flex-col-reverse gap-px">
            {grouped.map((evt) => {
              const color = agentColor(evt.stream);
              const label = agentLabel(evt.stream);
              const jobId = evt.data?.job_id || "";
              const eventType = evt.data?.event_type || "";
              const timestamp = evt.data?.timestamp
                ? new Date(evt.data.timestamp).toLocaleTimeString()
                : "";
              const preview =
                evt.data?.exception_type ||
                evt.data?.reason ||
                evt.data?.message ||
                eventType ||
                "";
              const isEpoch = eventType === "EPOCH_COMPLETE";
              const loss = evt.data?.train_loss ? parseFloat(evt.data.train_loss) : null;
              const valLoss = evt.data?.val_loss ? parseFloat(evt.data.val_loss) : null;

              return (
                <div
                  key={evt.id}
                  className="flex items-center gap-3 px-3 h-7 text-xs hover:bg-[var(--color-surface)] transition-colors border-l-2"
                  style={{ borderLeftColor: color }}
                >
                  {/* Timestamp */}
                  <span className="text-[var(--color-text-muted)] font-mono text-[10px] w-[70px] shrink-0">
                    {timestamp}
                  </span>

                  {/* Agent tag — only shown when not grouped */}
                  {!evt.sameAgent && (
                    <span
                      className="font-mono text-[10px] font-semibold w-[70px] shrink-0"
                      style={{ color }}
                    >
                      {label}
                    </span>
                  )}
                  {evt.sameAgent && <span className="w-[70px] shrink-0" />}

                  {/* Job ID */}
                  {jobId && (
                    <span className="text-[var(--color-text-muted)] font-mono text-[10px] w-[70px] shrink-0">
                      [{jobId.slice(0, 8)}]
                    </span>
                  )}

                  {/* Sparkline for epoch events */}
                  {isEpoch && loss !== null && (
                    <Sparkline values={[loss, valLoss ?? loss]} color={color} />
                  )}

                  {/* Message */}
                  <span className="text-[var(--color-text-secondary)] leading-relaxed truncate min-w-0">
                    {preview}
                  </span>

                  {/* Loss values */}
                  {isEpoch && loss !== null && (
                    <span className="text-[var(--color-text-muted)] font-mono text-[10px] shrink-0 ml-auto">
                      {loss.toFixed(4)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
