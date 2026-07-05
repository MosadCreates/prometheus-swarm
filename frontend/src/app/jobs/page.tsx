"use client";

import { useEffect, useState } from "react";
import { PipelineRail, type PipelineState } from "@/shared/layout/PipelineRail";
import { Search, Filter } from "lucide-react";

interface Job {
  id: string;
  problem_description?: string;
  status?: string;
  stage?: string;
}

const STATUS_PILL: Record<string, { color: string; label: string }> = {
  completed: { color: "var(--color-cyan)", label: "Completed" },
  COMPLETED: { color: "var(--color-cyan)", label: "Completed" },
  pass: { color: "var(--color-cyan)", label: "Completed" },
  running: { color: "var(--color-accent)", label: "Running" },
  QUEUED: { color: "var(--color-text-muted)", label: "Queued" },
  ESCALATED: { color: "var(--color-alert)", label: "Escalated" },
  failed: { color: "var(--color-alert)", label: "Failed" },
};

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

function getStatusPill(s?: string) {
  if (!s) return { color: "var(--color-text-muted)", label: "Unknown" };
  return STATUS_PILL[s] || { color: "var(--color-text-muted)", label: s };
}

function MiniPipelineDot({ stage, state }: { stage: string; state: PipelineState }) {
  const isCompleted = state.completed.includes(stage);
  const isActive = state.active === stage;
  return (
    <span
      className="inline-block w-1.5 h-1.5 rounded-full transition-all"
      style={{
        backgroundColor: isActive ? "var(--color-accent)" : isCompleted ? "var(--color-text-muted)" : "var(--color-border)",
        boxShadow: isActive ? "0 0 4px rgba(255,107,53,0.5)" : "none",
      }}
    />
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    fetch("/api/jobs")
      .then((r) => r.json())
      .then((d) => setJobs(d.jobs || []))
      .finally(() => setLoading(false));
  }, []);

  const filtered = jobs.filter((job) => {
    const statusMatch = filterStatus === "all" || (job.status?.toLowerCase() ?? "") === filterStatus;
    const searchMatch = !searchQuery || (job.problem_description ?? "").toLowerCase().includes(searchQuery.toLowerCase());
    return statusMatch && searchMatch;
  });

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <h1 className="text-sm font-semibold text-[var(--color-text-primary)] mb-6">Job History</h1>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center gap-1.5 px-2 py-1.5 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-[var(--color-surface)]">
          <Filter className="w-3 h-3 text-[var(--color-text-muted)]" />
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-transparent text-xs text-[var(--color-text-secondary)] border-none outline-none cursor-pointer font-mono"
            style={{ fontSize: "11px" }}
          >
            <option value="all">All</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="failed">Failed</option>
            <option value="escalated">Escalated</option>
            <option value="queued">Queued</option>
          </select>
        </div>
        <div className="flex items-center gap-1.5 px-2 py-1.5 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-[var(--color-surface)] flex-1 max-w-xs">
          <Search className="w-3 h-3 text-[var(--color-text-muted)]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by description..."
            className="bg-transparent text-xs text-[var(--color-text-secondary)] border-none outline-none flex-1 font-mono placeholder-[var(--color-text-muted)]"
            style={{ fontSize: "11px" }}
          />
        </div>
        <span className="text-[10px] text-[var(--color-text-muted)] font-mono">{filtered.length} jobs</span>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <span className="w-4 h-4 rounded-full border border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin" />
        </div>
      )}

      {/* Empty */}
      {!loading && filtered.length === 0 && (
        <div className="text-center py-16 text-xs text-[var(--color-text-muted)] font-mono">
          No jobs found.
        </div>
      )}

      {/* Table */}
      {!loading && filtered.length > 0 && (
        <div className="border border-[var(--color-border)]">
          {/* Header */}
          <div className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[140px] uppercase tracking-wider">Job ID</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] flex-1 uppercase tracking-wider">Problem</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[120px] uppercase tracking-wider">Stage</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[80px] uppercase tracking-wider">Status</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[60px] uppercase tracking-wider">Cost</span>
          </div>

          {/* Rows */}
          <div className="divide-y divide-[var(--color-border)]">
            {filtered.map((job) => {
              const pill = getStatusPill(job.status);
              const pipelineState = getPipelineState(job.stage);
              return (
                <a
                  key={job.id}
                  href={`/jobs/${encodeURIComponent(job.id)}`}
                  className="flex items-center gap-4 px-4 py-3 hover:bg-[var(--color-surface)] transition-colors no-underline"
                >
                  {/* Job ID */}
                  <span className="text-xs font-mono text-[var(--color-text-secondary)] w-[140px] shrink-0 truncate">
                    {job.id.slice(0, 22)}
                  </span>

                  {/* Problem */}
                  <span className="text-xs text-[var(--color-text-primary)] flex-1 truncate">
                    {job.problem_description?.slice(0, 80) || "(no description)"}
                  </span>

                  {/* Mini pipeline dots */}
                  <div className="flex items-center gap-1.5 w-[120px] shrink-0">
                    {STAGE_ORDER.map((stage) => (
                      <MiniPipelineDot key={stage} stage={stage} state={pipelineState} />
                    ))}
                  </div>

                  {/* Status pill */}
                  <span
                    className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold w-[80px] shrink-0 text-center justify-center"
                    style={{
                      backgroundColor: `${pill.color}15`,
                      color: pill.color,
                    }}
                  >
                    {pill.label}
                  </span>

                  {/* Cost */}
                  <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[60px] shrink-0 text-right">
                    &mdash;
                  </span>
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
