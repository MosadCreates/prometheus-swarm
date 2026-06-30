"use client";

import { useEffect, useRef, useState } from "react";

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

const AGENT_COLORS: Record<string, string> = {
  scout_output: "#22c55e",
  forge_output: "#3b82f6",
  furnace_feed: "#f59e0b",
  furnace_output: "#f59e0b",
  furnace_crash: "#ef4444",
  dissect_output: "#a855f7",
  arbiter_output: "#06b6d4",
  harbor_output: "#ec4899",
  orchestrator_output: "#64748b",
};

const AGENT_LABELS: Record<string, string> = {
  scout_output: "Scout",
  forge_output: "Forge",
  furnace_feed: "Furnace (epoch)",
  furnace_output: "Furnace",
  furnace_crash: "Furnace (crash)",
  dissect_output: "Dissect",
  arbiter_output: "Arbiter",
  harbor_output: "Harbor",
  orchestrator_output: "Orchestrator",
};

export default function FeedPage() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
        setEvents((prev) => [parsed, ...prev].slice(0, 200));
      } catch {
        // ignore
      }
    };

    evtSource.onerror = () => {
      setConnected(false);
      setError("Connection lost. Retrying...");
    };

    return () => evtSource.close();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "16px" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 20,
          borderBottom: "1px solid #1e1e2e",
          paddingBottom: 12,
        }}
      >
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>
          Prometheus Swarm
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: connected ? "#22c55e" : "#ef4444",
              display: "inline-block",
            }}
          />
          <span style={{ fontSize: 13, color: "#94a3b8" }}>
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </header>

      {error && (
        <div
          style={{
            background: "#1e1e2e",
            border: "1px solid #ef4444",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: 13,
            color: "#fca5a5",
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          display: "flex",
          flexDirection: "column-reverse",
          gap: 4,
          maxHeight: "calc(100vh - 120px)",
          overflowY: "auto",
        }}
      >
        {events.map((evt) => {
          const color = AGENT_COLORS[evt.stream] || "#64748b";
          const label = AGENT_LABELS[evt.stream] || evt.stream;
          const jobId = evt.data?.job_id || "";
          const eventType = evt.data?.event_type || "";
          const timestamp = evt.data?.timestamp
            ? new Date(evt.data.timestamp).toLocaleTimeString()
            : "";

          return (
            <div
              key={evt.id}
              style={{
                display: "flex",
                gap: 10,
                padding: "6px 10px",
                borderRadius: 4,
                background: "#14141f",
                borderLeft: `3px solid ${color}`,
                fontSize: 13,
                fontFamily: "monospace",
              }}
            >
              <span style={{ color: "#64748b", minWidth: 70, fontSize: 11 }}>
                {timestamp}
              </span>
              <span
                style={{
                  color,
                  fontWeight: 600,
                  minWidth: 100,
                  fontSize: 12,
                }}
              >
                {label}
              </span>
              {jobId && (
                <span style={{ color: "#94a3b8", fontSize: 11, minWidth: 90 }}>
                  [{jobId.slice(0, 8)}]
                </span>
              )}
              <span style={{ color: "#e0e0e0", flex: 1 }}>
                {eventType || evt.data?.exception_type || evt.data?.reason || JSON.stringify(evt.data).slice(0, 120)}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {events.length === 0 && !error && (
        <div
          style={{
            textAlign: "center",
            color: "#64748b",
            padding: 60,
            fontSize: 14,
          }}
        >
          Waiting for events...
        </div>
      )}
    </div>
  );
}
