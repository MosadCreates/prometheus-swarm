"use client";

import { useEffect, useState } from "react";

interface Job {
  id: string;
  problem_description?: string;
  architecture_decision_id?: string;
  status?: string;
  current_agent?: string;
  api_cost?: string;
  file_path?: string;
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

  const statusColor = (s?: string) => {
    if (!s) return "#64748b";
    if (s === "completed") return "#22c55e";
    if (s === "running") return "#f59e0b";
    if (s === "failed") return "#ef4444";
    return "#64748b";
  };

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: "16px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>
        Job History
      </h1>

      {loading ? (
        <p style={{ color: "#64748b" }}>Loading...</p>
      ) : jobs.length === 0 ? (
        <p style={{ color: "#64748b" }}>No jobs found in Redis.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {jobs.map((job) => (
            <a
              key={job.id}
              href={`/jobs/${encodeURIComponent(job.id)}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 14px",
                borderRadius: 6,
                background: "#14141f",
                border: "1px solid #1e1e2e",
                textDecoration: "none",
                fontSize: 13,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: statusColor(job.status),
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  color: "#94a3b8",
                  minWidth: 140,
                  fontSize: 11,
                  fontFamily: "monospace",
                }}
              >
                {job.id.slice(0, 22)}
              </span>
              <span style={{ color: "#e0e0e0", flex: 1 }}>
                {job.problem_description?.slice(0, 80) || "(no description)"}
              </span>
              {job.status && (
                <span
                  style={{
                    color: statusColor(job.status),
                    fontSize: 11,
                    fontWeight: 600,
                    minWidth: 70,
                    textAlign: "right",
                  }}
                >
                  {job.status}
                </span>
              )}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
