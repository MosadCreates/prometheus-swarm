"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { PipelineRail, type PipelineState } from "@/shared/layout/PipelineRail";

interface Computed {
  endpoint_url: string | null;
  pass_fail: string | null;
  best_metric: { value: number; label: string } | null;
  architecture: string | null;
}

const STAGE_ORDER = ["scout", "forge", "furnace", "dissect", "arbiter", "harbor"];

function getPipelineState(stage?: string): PipelineState {
  if (!stage) return { completed: [], active: null };
  const idx = STAGE_ORDER.indexOf(stage);
  if (idx === -1) return { completed: [], active: null };
  return {
    completed: STAGE_ORDER.slice(0, idx),
    active: stage,
  };
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
  return stream;
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Record<string, string> | null>(null);
  const [computed, setComputed] = useState<Computed | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  const fetchJob = useCallback(async () => {
    try {
      const r = await fetch(`/api/jobs/${encodeURIComponent(id)}`);
      const d = await r.json();
      setData(d.data || {});
      setHistory(d.history || []);
      setComputed(d.computed || null);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchJob();
    const interval = setInterval(fetchJob, 3000);
    return () => clearInterval(interval);
  }, [fetchJob]);

  const status = data?.status || "unknown";
  const isLive = status === "completed" || status === "pass";
  const pipelineState = getPipelineState(data?.stage);
  const primaryMetric = computed?.best_metric?.value ?? null;
  const metricLabel = computed?.best_metric?.label ?? "";

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-var(--header-height))] bg-[var(--color-bg)]">
        <span className="w-4 h-4 rounded-full border border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16">
        <div className="border border-[var(--color-border)] bg-[var(--color-surface)] p-10 text-center">
          <p className="text-sm text-[var(--color-text-secondary)] font-semibold mb-1">Job not found</p>
          <p className="text-xs text-[var(--color-text-muted)] font-mono">{id}</p>
          <a href="/jobs" className="text-xs text-[var(--color-cyan)] hover:underline mt-4 inline-block">
            &larr; Back to jobs
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--color-bg)]" style={{ minHeight: "calc(100vh - var(--header-height))" }}>
      {/* Horizontal pipeline rail */}
      <div className="border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <a href="/jobs" className="text-[10px] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors no-underline font-mono">
              &larr; Jobs
            </a>
            <h1 className="text-xs font-mono font-semibold text-[var(--color-text-primary)]">
              {id?.slice(0, 22)}
            </h1>
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold"
              style={{
                backgroundColor: isLive ? "var(--color-cyan)15" : "var(--color-text-muted)15",
                color: isLive ? "var(--color-cyan)" : "var(--color-text-muted)",
              }}
            >
              {isLive ? "Live" : status}
            </span>
          </div>
        </div>
        <PipelineRail state={pipelineState} orientation="horizontal" />
      </div>

      {/* Metrics strip */}
      <div className="flex items-stretch border-b border-[var(--color-border)]">
        <div className="flex-1 px-6 py-4 border-r border-[var(--color-border)] last:border-r-0">
          <div className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
            {primaryMetric !== null ? metricLabel || "Best Metric" : "Best Metric"}
          </div>
          <div className="text-xl font-mono font-semibold text-[var(--color-text-primary)]">
            {primaryMetric !== null ? primaryMetric.toFixed(4) : "—"}
          </div>
        </div>
        <div className="flex-1 px-6 py-4 border-r border-[var(--color-border)] last:border-r-0">
          <div className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
            Duration
          </div>
          <div className="text-xl font-mono font-semibold text-[var(--color-text-primary)]">
            {data.duration ? `${data.duration}s` : "—"}
          </div>
        </div>
        <div className="flex-1 px-6 py-4">
          <div className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
            Decision
          </div>
          <div
            className="text-xl font-mono font-semibold"
            style={{
              color:
                computed?.pass_fail === "pass"
                  ? "var(--color-cyan)"
                  : computed?.pass_fail === "retry"
                  ? "var(--color-warning)"
                  : "var(--color-text-muted)",
            }}
          >
            {computed?.pass_fail ? computed.pass_fail.toUpperCase() : "—"}
          </div>
        </div>
      </div>

      {/* Two-column body */}
      <div className="flex" style={{ height: "calc(100vh - var(--header-height) - 180px)" }}>
        {/* Left: Mission brief */}
        <div className="w-80 shrink-0 border-r border-[var(--color-border)] overflow-y-auto p-5">
          <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-4">Mission Brief</h2>

          <div className="space-y-4">
            <div>
              <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Problem</div>
              <div className="text-xs text-[var(--color-text-primary)] leading-relaxed">
                {data.problem_description || "(no description)"}
              </div>
            </div>

            <div className="hairline" />

            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Architecture</div>
                <div className="text-xs font-mono text-[var(--color-text-secondary)]">
                  {computed?.architecture || data.architecture_decision_id || "Pending"}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Crash Recovery</div>
                <div className="text-xs font-mono text-[var(--color-text-secondary)]">
                  {data.crash_count || "0"} recovered
                </div>
              </div>
            </div>

            <div className="hairline" />

            <div>
              <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Submitted</div>
              <div className="text-xs font-mono text-[var(--color-text-secondary)]">
                {data.created_at ? new Date(data.created_at).toLocaleString() : "—"}
              </div>
            </div>

            {data.dataset_path && (
              <>
                <div className="hairline" />
                <div>
                  <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Dataset</div>
                  <div className="text-xs font-mono text-[var(--color-text-secondary)] truncate">
                    {data.dataset_path}
                  </div>
                </div>
              </>
            )}

            {isLive && computed?.endpoint_url && (
              <>
                <div className="hairline" />
                <div>
                  <div className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">Endpoint</div>
                  <div className="flex gap-1">
                    <code className="flex-1 text-[10px] font-mono text-[var(--color-cyan)] truncate bg-[var(--color-surface)] px-2 py-1 rounded-[var(--radius-sm)] border border-[var(--color-border)]">
                      {computed.endpoint_url}
                    </code>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(computed.endpoint_url!);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 2000);
                      }}
                      className="px-2 py-1 text-[10px] font-mono border border-[var(--color-border)] rounded-[var(--radius-sm)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface)] transition-colors bg-[var(--color-bg)]"
                    >
                      {copied ? "OK" : "Copy"}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Right: Event log */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-5 py-3 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
            <h2 className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider">
              Event Log
              <span className="ml-2 text-[var(--color-text-muted)]">({history.length})</span>
            </h2>
          </div>

          {history.length === 0 ? (
            <div className="flex items-center justify-center h-full text-xs text-[var(--color-text-muted)] font-mono">
              No events recorded.
            </div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {history.map((evt: any, i: number) => {
                const prev = history[i - 1];
                const sameAgent = prev ? agentLabel(prev.stream) === agentLabel(evt.stream) : false;
                const color = agentColor(evt.stream || "");
                const label = agentLabel(evt.stream || "");
                return (
                  <div
                    key={evt.id}
                    className="flex items-start gap-3 px-5 py-2.5 text-xs hover:bg-[var(--color-surface)] transition-colors border-l-2"
                    style={{ borderLeftColor: color }}
                  >
                    <span className="text-[var(--color-text-muted)] font-mono text-[10px] w-[70px] shrink-0 pt-0.5">
                      {(evt.id || "").slice(0, 8)}
                    </span>
                    {!sameAgent && (
                      <span
                        className="font-mono text-[10px] font-semibold w-[80px] shrink-0 pt-0.5"
                        style={{ color }}
                      >
                        {label}
                      </span>
                    )}
                    {sameAgent && <span className="w-[80px] shrink-0" />}
                    <span className="text-[var(--color-text-muted)] text-[10px] font-mono w-[90px] shrink-0 pt-0.5">
                      {evt.event_type || ""}
                    </span>
                    <span className="text-[var(--color-text-secondary)] leading-relaxed break-words min-w-0 pt-0.5">
                      {evt.exception_type || evt.reason || evt.message || ""}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
