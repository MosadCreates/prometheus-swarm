"use client";

import { useEffect, useState } from "react";

interface DriftEvent {
  id: string;
  job_id: string;
  psi: number;
  feature: string;
  timestamp: string;
}

export default function DriftPage() {
  const [events, setEvents] = useState<DriftEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/drift")
      .then((r) => r.json())
      .then((d) => {
        setEvents(d.driftEvents || []);
      })
      .finally(() => setLoading(false));
  }, []);

  const psiColor = (psi: number) => {
    if (psi > 0.2) return "#ef4444";
    if (psi > 0.1) return "#f59e0b";
    return "#22c55e";
  };

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: "16px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 16 }}>
        PSI Drift Monitor
      </h1>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
          marginBottom: 24,
        }}
      >
        <div
          style={{
            padding: 16,
            borderRadius: 6,
            background: "#14141f",
            border: "1px solid #1e1e2e",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Status</div>
          <div style={{ fontSize: 14, color: events.length > 0 && events.some((e) => e.psi > 0.2) ? "#ef4444" : "#22c55e", fontWeight: 600 }}>
            {events.length > 0 && events.some((e) => e.psi > 0.2) ? "Drift Detected" : "Stable"}
          </div>
        </div>
        <div
          style={{
            padding: 16,
            borderRadius: 6,
            background: "#14141f",
            border: "1px solid #1e1e2e",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Total Alerts</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#e0e0e0" }}>{events.length}</div>
        </div>
        <div
          style={{
            padding: 16,
            borderRadius: 6,
            background: "#14141f",
            border: "1px solid #1e1e2e",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Monitored Features</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#e0e0e0" }}>
            {new Set(events.map((e) => e.feature)).size}
          </div>
        </div>
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
        Alert History
      </h2>

      {loading ? (
        <p style={{ color: "#64748b" }}>Loading...</p>
      ) : events.length === 0 ? (
        <p style={{ color: "#64748b" }}>No drift alerts recorded yet.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {events.map((evt) => {
            const barWidth = Math.min(evt.psi * 100, 100);
            return (
              <div
                key={evt.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 12px",
                  borderRadius: 4,
                  background: "#14141f",
                  border: "1px solid #1e1e2e",
                  fontSize: 12,
                }}
              >
                <span style={{ color: "#64748b", minWidth: 80, fontSize: 11 }}>
                  {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ""}
                </span>
                <span style={{ color: "#94a3b8", minWidth: 100, fontFamily: "monospace" }}>
                  {evt.job_id.slice(0, 8)}
                </span>
                <span style={{ color: "#e0e0e0", minWidth: 80 }}>{evt.feature}</span>
                <div
                  style={{
                    flex: 1,
                    height: 8,
                    borderRadius: 4,
                    background: "#1e1e2e",
                    position: "relative",
                  }}
                >
                  <div
                    style={{
                      width: `${barWidth}%`,
                      height: "100%",
                      borderRadius: 4,
                      background: psiColor(evt.psi),
                      transition: "width 0.3s",
                    }}
                  />
                </div>
                <span
                  style={{
                    color: psiColor(evt.psi),
                    fontWeight: 600,
                    minWidth: 50,
                    textAlign: "right",
                  }}
                >
                  {evt.psi.toFixed(3)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div
        style={{
          marginTop: 24,
          padding: 12,
          borderRadius: 6,
          background: "#14141f",
          border: "1px solid #1e1e2e",
          fontSize: 12,
          color: "#64748b",
          lineHeight: 1.6,
        }}
      >
        <strong style={{ color: "#94a3b8" }}>PSI Thresholds</strong>
        <br />
        PSI &lt; 0.1: No drift (green) &mdash; 0.1 &ndash; 0.2: Moderate drift (amber) &mdash; &gt; 0.2:
        Significant drift (red) &mdash; triggers automatic retrain via Scout.
      </div>
    </div>
  );
}
