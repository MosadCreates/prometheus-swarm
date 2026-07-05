"use client";

import { useState, useEffect } from "react";
import CodeBlock from "./CodeBlock";
import TrainingChart from "./TrainingChart";
import type { EpochData } from "./TrainingChart";

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

const AGENT_META: Record<string, { color: string; label: string }> = {
  scout_output: { color: "#10b981", label: "Scout" },
  forge_output: { color: "#3b82f6", label: "Forge" },
  furnace_feed: { color: "#f59e0b", label: "Furnace" },
  furnace_output: { color: "#f59e0b", label: "Furnace" },
  furnace_crash: { color: "#ef4444", label: "Furnace" },
  dissect_output: { color: "#8b5cf6", label: "Dissect" },
  arbiter_output: { color: "#06b6d4", label: "Arbiter" },
  harbor_output: { color: "#ec4899", label: "Harbor" },
};

export default function AgentCard({ event }: { event: StreamEvent }) {
  const [expanded, setExpanded] = useState(false);
  const [scriptContent, setScriptContent] = useState<string | null>(null);
  const [epochData, setEpochData] = useState<EpochData[]>([]);

  const meta = AGENT_META[event.stream] || { color: "#64748b", label: event.stream };
  const eventType = event.data?.event_type || "";
  const isActive = eventType === "TRAINING_COMPLETE" || eventType === "ENDPOINT_LIVE" ? false : true;

  useEffect(() => {
    if (eventType === "TRAINING_SCRIPT_READY" && event.data?.script_path) {
      fetch(event.data.script_path)
        .then((r) => r.text())
        .then(setScriptContent)
        .catch(() => setScriptContent("// Could not load script"));
    }
  }, [eventType, event.data?.script_path]);

  useEffect(() => {
    if (eventType === "EPOCH_COMPLETE") {
      const ep = parseInt(event.data?.epoch || "0");
      const tl = event.data?.train_loss ? parseFloat(event.data.train_loss) : undefined;
      const vl = event.data?.val_loss ? parseFloat(event.data.val_loss) : undefined;
      if (ep && tl !== undefined) {
        setEpochData((prev) => [...prev, { epoch: ep, train_loss: tl, val_loss: vl }]);
        setExpanded(true);
      }
    }
  }, [eventType, event.data?.epoch, event.data?.train_loss, event.data?.val_loss]);

  function renderContent() {
    switch (eventType) {
      case "MISSION_BRIEF_READY":
        return (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              {event.data?.task_type && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: "#10b98118", color: "#10b981" }}>
                  {event.data.task_type}
                </span>
              )}
              {event.data?.modality && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: "#3b82f618", color: "#3b82f6" }}>
                  {event.data.modality}
                </span>
              )}
              {event.data?.evaluation_metric && (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: "#f59e0b18", color: "#f59e0b" }}>
                  Metric: {event.data.evaluation_metric}
                </span>
              )}
            </div>
            {event.data?.data_warnings && (
              <div className="text-[11px] text-[#f59e0b] bg-[#F0EDE8] rounded-lg px-3 py-2 border border-[#E8E5DF]">
                {event.data.data_warnings}
              </div>
            )}
          </div>
        );

      case "TRAINING_SCRIPT_READY":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold" style={{ background: "#3b82f618", color: "#3b82f6" }}>
                {event.data?.architecture || "Architecture selected"}
              </span>
              {event.data?.script_path && (
                <span className="text-[10px] text-[#8B8982] font-mono">{event.data.script_path.split("/").pop()}</span>
              )}
            </div>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[11px] text-[#8B8982] hover:text-[#1C1B19] bg-transparent border-none cursor-pointer"
            >
              {expanded ? "Hide code" : "View generated code →"}
            </button>
            {expanded && scriptContent && <CodeBlock code={scriptContent} language="python" fileName={event.data?.script_path?.split("/").pop()} />}
          </div>
        );

      case "EPOCH_COMPLETE": {
        const ep = event.data?.epoch || "0";
        const tl = event.data?.train_loss || "";
        const vl = event.data?.val_loss || "";
        const eta = event.data?.eta_seconds || "";
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-xs text-[#1C1B19]">
              <span>Epoch <strong>{ep}</strong></span>
              {tl && <span>Train: <strong className="text-[#C96442]">{parseFloat(tl).toFixed(4)}</strong></span>}
              {vl && <span>Val: <strong className="text-[#8B8982]">{parseFloat(vl).toFixed(4)}</strong></span>}
              {eta && <span className="text-[#8B8982]">ETA: {parseInt(eta) > 60 ? `${Math.round(parseInt(eta)/60)}m` : `${eta}s`}</span>}
            </div>
            {epochData.length > 1 && <TrainingChart data={epochData} />}
          </div>
        );
      }

      case "CRASH_EVENT":
        return (
          <div className="space-y-2">
            <div className="p-3 rounded-xl bg-[#F0EDE8] border border-[#E8E5DF]">
              <div className="text-xs font-semibold text-[#C96442] mb-1">
                {event.data?.exception_type || "Error"}
              </div>
              <div className="text-[11px] text-[#1C1B19] font-mono whitespace-pre-wrap">
                {event.data?.exception_message || "Unknown error"}
              </div>
            </div>
          </div>
        );

      case "RESUME_TRAINING":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-[#10b981]">
              <span>Patch applied — resuming training</span>
            </div>
            {event.data?.patch_id && (
              <span className="text-[10px] text-[#8B8982] font-mono">Patch: {event.data.patch_id.slice(0, 8)}</span>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-[11px] text-[#8B8982] hover:text-[#1C1B19] bg-transparent border-none cursor-pointer"
            >
              {expanded ? "Hide diff" : "View patch diff →"}
            </button>
            {expanded && event.data?.diff_applied && (
              <CodeBlock code={event.data.diff_applied} language="diff" fileName="patch.diff" />
            )}
          </div>
        );

      case "TRAINING_COMPLETE":
        return (
          <div className="flex items-center gap-2 text-xs text-[#10b981]">
            <span>Training complete</span>
            {event.data?.best_val_metric && (
              <span className="text-[#8B8982]">Best: <strong>{parseFloat(event.data.best_val_metric).toFixed(4)}</strong></span>
            )}
            {event.data?.total_epochs && <span className="text-[#8B8982]">{event.data.total_epochs} epochs</span>}
          </div>
        );

      case "EVALUATION_PASS":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#10b981]">Model passed evaluation</span>
            </div>
            <div className="flex gap-2">
              <div className="flex-1 p-3 rounded-xl bg-[#F7F6F3] border border-[#E8E5DF] text-center">
                <div className="text-[18px] font-bold text-[#C96442]">
                  {event.data?.primary_metric_value ? parseFloat(event.data.primary_metric_value).toFixed(4) : "—"}
                </div>
                <div className="text-[10px] text-[#8B8982] mt-0.5">{event.data?.primary_metric || "Metric"}</div>
              </div>
              <div className="flex-1 p-3 rounded-xl bg-[#F7F6F3] border border-[#E8E5DF] text-center">
                <div className="text-[18px] font-bold text-[#10b981]">PASS</div>
                <div className="text-[10px] text-[#8B8982] mt-0.5">Decision</div>
              </div>
            </div>
          </div>
        );

      case "EVALUATION_RETRY":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#f59e0b]">Retrying with different architecture</span>
            </div>
            {event.data?.reason && <div className="text-[11px] text-[#1C1B19] bg-[#F0EDE8] rounded-lg px-3 py-2 border border-[#E8E5DF]">{event.data.reason}</div>}
          </div>
        );

      case "ENDPOINT_LIVE":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#ec4899]">Model deployed!</span>
            </div>
            {event.data?.endpoint_url && (
              <div className="flex items-center gap-2 p-2 rounded-lg bg-[#F7F6F3] border border-[#E8E5DF]">
                <code className="flex-1 text-[11px] font-mono text-[#1C1B19] break-all">{event.data.endpoint_url}</code>
                <button
                  onClick={() => navigator.clipboard.writeText(event.data!.endpoint_url!).then(() => {}).catch(() => {})}
                  className="text-[11px] text-[#8B8982] hover:text-[#1C1B19] bg-transparent border-none cursor-pointer shrink-0"
                >
                  Copy
                </button>
              </div>
            )}
            {event.data?.val_metric && (
              <div className="text-[11px] text-[#8B8982]">
                Validation metric: <strong>{parseFloat(event.data.val_metric).toFixed(4)}</strong>
                {event.data?.p95_latency_ms && <span className="ml-3">P95 latency: <strong>{event.data.p95_latency_ms}ms</strong></span>}
              </div>
            )}
          </div>
        );

      case "ESCALATE":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-[#f43f5e]">System escalated — needs human review</span>
            </div>
            {event.data?.reason && <div className="text-[11px] text-[#1C1B19] bg-[#F0EDE8] rounded-lg px-3 py-2 border border-[#E8E5DF]">{event.data.reason}</div>}
          </div>
        );

      case "JOB_FAILED":
        return (
          <div className="flex items-center gap-2 text-xs text-[#f43f5e]">
            <span>Job failed — {event.data?.reason || "unknown reason"}</span>
          </div>
        );

      case "DRIFT_ALERT":
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-[#f59e0b]">
              <span>Drift detected</span>
            </div>
            {event.data?.psi_score && (
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 rounded-full bg-[#E8E5DF] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#f59e0b]"
                    style={{ width: `${Math.min(100, parseFloat(event.data.psi_score) * 100)}%` }}
                  />
                </div>
                <span className="text-[11px] text-[#8B8982] font-mono">
                  PSI: {parseFloat(event.data.psi_score).toFixed(3)}
                </span>
              </div>
            )}
          </div>
        );

      default:
        return <div className="text-xs text-[#8B8982]">{Object.entries(event.data || {}).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(", ")}</div>;
    }
  }

  return (
    <div
      className="rounded-xl border-l-[3px] bg-white border border-[#E8E5DF] p-3 shadow-sm"
      style={{ borderLeftColor: meta.color }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="w-1.5 h-1.5 rounded-full" style={{ background: isActive ? meta.color : "#94a3b8" }} />
        <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
        <span className="text-[10px] text-[#8B8982] font-mono">{eventType.replace(/_/g, " ").toLowerCase()}</span>
        {event.data?.timestamp && (
          <span className="text-[10px] text-[#8B8982] ml-auto">
            {new Date(event.data.timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>
      {renderContent()}
    </div>
  );
}
