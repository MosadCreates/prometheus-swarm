"use client";

import { useEffect, useState } from "react";

interface Job {
  id: string;
  problem_description?: string;
  status?: string;
}

const STATUS_STYLES: Record<string, { dot: string; label: string }> = {
  completed: { dot: "#10b981", label: "Completed" },
  COMPLETED: { dot: "#10b981", label: "Completed" },
  running: { dot: "#f59e0b", label: "Running" },
  QUEUED: { dot: "#94a3b8", label: "Queued" },
  ESCALATED: { dot: "#f43f5e", label: "Escalated" },
  failed: { dot: "#f43f5e", label: "Failed" },
  escalated: { dot: "#f43f5e", label: "Escalated" },
};

function getStatusStyle(s?: string) {
  if (!s) return { dot: "#94a3b8", label: "Unknown" };
  return STATUS_STYLES[s] || { dot: "#94a3b8", label: s };
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/jobs")
      .then((r) => r.json())
      .then((d) => setJobs(d.jobs || []))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="font-display text-lg text-[#1C1B19] mb-8">Job History</h1>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <span className="w-5 h-5 rounded-full border-2 border-[#E8E5DF] border-t-[#C96442] animate-spin" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-16 text-sm text-[#8B8982]">
          No jobs found.
        </div>
      ) : (
        <div className="bg-white border border-[#E8E5DF] rounded-xl overflow-hidden shadow-sm">
          <div className="divide-y divide-[#E8E5DF]">
            {jobs.map((job) => {
              const ss = getStatusStyle(job.status);
              return (
                <a
                  key={job.id}
                  href={`/jobs/${encodeURIComponent(job.id)}`}
                  className="flex items-center gap-4 px-5 py-3.5 hover:bg-[#F7F6F3] transition-colors no-underline"
                >
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: ss.dot }} />
                  <span className="text-xs font-mono text-[#8B8982] min-w-[140px]">
                    {job.id.slice(0, 22)}
                  </span>
                  <span className="text-sm text-[#1C1B19] flex-1 truncate">
                    {job.problem_description?.slice(0, 80) || "(no description)"}
                  </span>
                  <span
                    className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0"
                    style={{
                      background: ss.dot + "18",
                      color: ss.dot,
                    }}
                  >
                    {ss.label}
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
