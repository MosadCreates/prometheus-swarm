"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";

interface Computed {
  endpoint_url: string | null;
  pass_fail: string | null;
  best_metric: { value: number; label: string } | null;
  architecture: string | null;
}

const AGENT_COLORS: Record<string, string> = {
  scout: "var(--color-agent-scout)",
  forge: "var(--color-agent-forge)",
  furnace: "var(--color-agent-furnace)",
  dissect: "var(--color-agent-dissect)",
  arbiter: "var(--color-agent-arbiter)",
  harbor: "var(--color-agent-harbor)",
};

function agentColor(stream: string): string {
  for (const key of Object.keys(AGENT_COLORS)) {
    if (stream.includes(key)) return AGENT_COLORS[key];
  }
  return "var(--color-text-muted)";
}

function agentLabel(stream: string): string {
  if (stream.includes("scout")) return "Scout";
  if (stream.includes("forge")) return "Forge";
  if (stream.includes("furnace_crash")) return "Furnace (crash)";
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

  const copyUrl = async () => {
    if (computed?.endpoint_url) {
      try {
        await navigator.clipboard.writeText(computed.endpoint_url);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {}
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-3.5rem)]">
        <span className="w-5 h-5 rounded-full border-2 border-[var(--color-border)] border-t-[var(--color-primary)] animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16">
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-10 text-center shadow-sm">
          <p className="text-sm text-[var(--color-text-secondary)] font-semibold mb-1">Job not found</p>
          <p className="text-xs text-[var(--color-text-muted)] font-mono">{id}</p>
          <a href="/jobs" className="text-xs text-[var(--color-primary)] hover:text-[var(--color-primary-hover)] mt-4 inline-block">
            &larr; Back to jobs
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-8 animate-fade-in">
      <a href="/jobs" className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors no-underline mb-6 inline-block">
        &larr; Back to jobs
      </a>

      <div className="flex items-center gap-3 mb-8">
        <h1 className="text-sm font-mono font-semibold text-[var(--color-text-primary)]">
          {id?.slice(0, 22)}
        </h1>
        <span
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold"
          style={{
            background: isLive ? "var(--color-success)" + "18" : "var(--color-text-muted)" + "18",
            color: isLive ? "var(--color-success)" : "var(--color-text-muted)",
          }}
        >
          {isLive ? "Live" : status}
        </span>
      </div>

      {isLive && computed?.endpoint_url && (
        <div className="mb-6 p-5 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-[var(--color-success)]" />
            <span className="text-xs font-semibold text-[var(--color-success)]">Your model is live</span>
          </div>
          <div className="flex gap-2">
            <code className="flex-1 px-4 py-2.5 rounded-[var(--radius-md)] bg-[var(--color-surface)] text-xs font-mono text-[var(--color-text-primary)] break-all border border-[var(--color-border)]">
              {computed.endpoint_url}
            </code>
            <button
              onClick={copyUrl}
              className={`px-4 py-2.5 rounded-[var(--radius-md)] text-xs font-semibold border transition-all duration-200 ${
                copied
                  ? "bg-[var(--color-success)] border-[var(--color-success)] text-white"
                  : "bg-[var(--color-surface)] border-[var(--color-border)] text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)]"
              }`}
            >
              {copied ? "Copied!" : "Copy URL"}
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 shadow-sm">
          <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mb-1.5">
            Problem
          </div>
          <div className="text-sm text-[var(--color-text-primary)] leading-relaxed">
            {data.problem_description || "(no description)"}
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 shadow-sm">
          <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mb-1.5">
            Architecture
          </div>
          <div className="text-sm text-[var(--color-text-primary)]">
            {computed?.architecture || data.architecture_decision_id || "Pending"}
          </div>
          {data.created_at && (
            <>
              <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mt-4 mb-1.5">
                Submitted
              </div>
              <div className="text-sm text-[var(--color-text-primary)]">
                {new Date(data.created_at).toLocaleString()}
              </div>
            </>
          )}
        </div>
      </div>

      {computed?.best_metric && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 shadow-sm">
            <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
              Best Metric
            </div>
            <div className="text-2xl font-bold text-[var(--color-primary)]">
              {computed.best_metric.value.toFixed(4)}
            </div>
            <div className="text-xs text-[var(--color-text-muted)] mt-0.5">{computed.best_metric.label}</div>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 shadow-sm">
            <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
              Decision
            </div>
            <div
              className="text-2xl font-bold"
              style={{
                color:
                  computed.pass_fail === "pass"
                    ? "var(--color-success)"
                    : computed.pass_fail === "retry"
                    ? "var(--color-warning)"
                    : "var(--color-text-muted)",
              }}
            >
              {computed.pass_fail ? computed.pass_fail.toUpperCase() : "Pending"}
            </div>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 shadow-sm">
            <div className="text-[10px] font-semibold text-[var(--color-text-muted)] uppercase tracking-wider mb-1">
              Crashes Recovered
            </div>
            <div className="text-2xl font-bold text-[var(--color-text-primary)]">
              {data.crash_count || "0"}
            </div>
          </div>
        </div>
      )}

      {history.length > 0 && (
        <details open={!isLive} className="mb-8">
          <summary className="text-xs font-semibold text-[var(--color-text-muted)] mb-4 cursor-pointer hover:text-[var(--color-text-primary)] transition-colors select-none">
            Event Log ({history.length})
          </summary>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4 shadow-sm max-h-[400px] overflow-y-auto">
            <div className="flex flex-col gap-1.5">
              {history.map((evt: any) => (
                <div
                  key={evt.id}
                  className="flex items-start gap-3 px-3 py-2 rounded-[var(--radius-md)] bg-[var(--color-surface)] border-l-[3px] text-xs animate-fade-in"
                  style={{ borderLeftColor: agentColor(evt.stream || "") }}
                >
                  <span className="text-[var(--color-text-muted)] font-mono text-[10px] min-w-[70px] pt-0.5 shrink-0">
                    {(evt.id || "").slice(0, 8)}
                  </span>
                  <span
                    className="font-semibold text-[11px] min-w-[100px] shrink-0 pt-0.5"
                    style={{ color: agentColor(evt.stream || "") }}
                  >
                    {agentLabel(evt.stream || "")}
                  </span>
                  <span className="text-[var(--color-text-muted)] text-[10px] min-w-[80px] pt-0.5 shrink-0">
                    {evt.event_type || ""}
                  </span>
                  <span className="text-[var(--color-text-primary)] leading-relaxed break-words min-w-0">
                    {evt.exception_type || evt.reason || evt.message || ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </details>
      )}
    </div>
  );
}
