"use client";

import { useEffect, useRef, useState } from "react";

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

const AGENT_STYLES: Record<string, { color: string; label: string }> = {
  scout_output: { color: "#10b981", label: "Scout" },
  forge_output: { color: "#3b82f6", label: "Forge" },
  furnace_feed: { color: "#f59e0b", label: "Furnace (epoch)" },
  furnace_output: { color: "#f59e0b", label: "Furnace" },
  furnace_crash: { color: "#ef4444", label: "Furnace (crash)" },
  dissect_output: { color: "#8b5cf6", label: "Dissect" },
  arbiter_output: { color: "#06b6d4", label: "Arbiter" },
  harbor_output: { color: "#ec4899", label: "Harbor" },
  orchestrator_output: { color: "#64748b", label: "Orch" },
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
    <div className="max-w-3xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-8">
        <h1 className="font-display text-lg text-[#1C1B19]">Live Feed</h1>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-[#10b981]" : "bg-[#f43f5e]"}`} />
          <span className="text-xs text-[#8B8982]">
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl border border-[#E8E5DF] bg-[#F0EDE8] text-xs text-[#C96442]">
          {error}
        </div>
      )}

      {events.length === 0 && !error && (
        <div className="text-center py-20 text-sm text-[#8B8982]">
          Waiting for events...
        </div>
      )}

      <div className="bg-white border border-[#E8E5DF] rounded-xl p-4">
        <div className="flex flex-col-reverse gap-1.5 max-h-[calc(100vh-12rem)] overflow-y-auto">
          {events.map((evt) => {
            const style = AGENT_STYLES[evt.stream] || { color: "#64748b", label: evt.stream };
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
              JSON.stringify(evt.data).slice(0, 120);

            return (
              <div
                key={evt.id}
                className="flex items-start gap-3 px-3 py-2 rounded-lg bg-[#F7F6F3] border-l-[3px] text-xs animate-fade-in"
                style={{ borderLeftColor: style.color }}
              >
                <span className="text-[#8B8982] font-mono text-[10px] min-w-[70px] pt-0.5 shrink-0">
                  {timestamp}
                </span>
                <span
                  className="font-semibold text-[11px] min-w-[90px] shrink-0 pt-0.5"
                  style={{ color: style.color }}
                >
                  {style.label}
                </span>
                {jobId && (
                  <span className="text-[#8B8982] font-mono text-[10px] min-w-[80px] pt-0.5 shrink-0">
                    [{jobId.slice(0, 8)}]
                  </span>
                )}
                <span className="text-[#1C1B19] leading-relaxed break-words min-w-0">
                  {preview}
                </span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
