"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Record<string, string> | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/jobs/${encodeURIComponent(id)}`)
      .then((r) => r.json())
      .then((d) => {
        setData(d.data || {});
        setHistory(d.history || []);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "16px", color: "#64748b" }}>
        Loading...
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "16px", color: "#ef4444" }}>
        Job not found: {id}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: "16px" }}>
      <a
        href="/jobs"
        style={{ color: "#3b82f6", fontSize: 13, textDecoration: "none", display: "inline-block", marginBottom: 12 }}
      >
        &larr; Back to jobs
      </a>

      <h1 style={{ fontSize: 18, fontWeight: 600, fontFamily: "monospace", marginBottom: 16 }}>
        {id}
      </h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
          marginBottom: 24,
        }}
      >
        {Object.entries(data).map(([key, val]) => (
          <div
            key={key}
            style={{
              padding: "8px 12px",
              borderRadius: 4,
              background: "#14141f",
              border: "1px solid #1e1e2e",
              fontSize: 12,
            }}
          >
            <div style={{ color: "#64748b", marginBottom: 4, fontSize: 11 }}>
              {key}
            </div>
            <div style={{ color: "#e0e0e0", wordBreak: "break-word" }}>
              {key.includes("brief") || key.includes("_space")
                ? `${val.slice(0, 200)}${val.length > 200 ? "..." : ""}`
                : val}
            </div>
          </div>
        ))}
      </div>

      {history.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
            Event History ({history.length})
          </h2>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              maxHeight: 400,
              overflowY: "auto",
            }}
          >
            {history.map((evt) => (
              <div
                key={evt.id}
                style={{
                  padding: "6px 10px",
                  borderRadius: 4,
                  background: "#14141f",
                  borderLeft: "3px solid #64748b",
                  fontSize: 12,
                  fontFamily: "monospace",
                }}
              >
                <span style={{ color: "#64748b", fontSize: 11 }}>
                  {evt.id?.slice(0, 20)}
                </span>{" "}
                <span style={{ color: "#94a3b8" }}>
                  {evt.event_type || evt.reason || JSON.stringify(evt).slice(0, 120)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
