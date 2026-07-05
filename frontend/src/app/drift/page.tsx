"use client";

import { useEffect, useState } from "react";

interface DriftEvent {
  id: string;
  job_id: string;
  psi: number;
  feature: string;
  timestamp: string;
}

function psiColor(psi: number): string {
  if (psi > 0.2) return "#f43f5e";
  if (psi > 0.1) return "#f59e0b";
  return "#10b981";
}

export default function DriftPage() {
  const [events, setEvents] = useState<DriftEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/drift")
      .then((r) => r.json())
      .then((d) => setEvents(d.driftEvents || []))
      .finally(() => setLoading(false));
  }, []);

  const hasActiveDrift = events.some((e) => e.psi > 0.2);
  const totalFeatures = new Set(events.map((e) => e.feature)).size;

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="font-display text-lg text-[#1C1B19] mb-8">PSI Drift Monitor</h1>

      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="bg-white border border-[#E8E5DF] rounded-xl p-5 text-center shadow-sm">
          <div className="text-[10px] font-semibold text-[#8B8982] uppercase tracking-wider mb-2">
            Status
          </div>
          <div className="text-sm font-semibold" style={{ color: hasActiveDrift ? "#f43f5e" : "#10b981" }}>
            {hasActiveDrift ? "Drift Detected" : "Stable"}
          </div>
        </div>
        <div className="bg-white border border-[#E8E5DF] rounded-xl p-5 text-center shadow-sm">
          <div className="text-[10px] font-semibold text-[#8B8982] uppercase tracking-wider mb-2">
            Total Alerts
          </div>
          <div className="text-2xl font-bold text-[#1C1B19]">{events.length}</div>
        </div>
        <div className="bg-white border border-[#E8E5DF] rounded-xl p-5 text-center shadow-sm">
          <div className="text-[10px] font-semibold text-[#8B8982] uppercase tracking-wider mb-2">
            Monitored Features
          </div>
          <div className="text-2xl font-bold text-[#1C1B19]">{totalFeatures}</div>
        </div>
      </div>

      <h2 className="text-sm font-semibold text-[#1C1B19] mb-4">Alert History</h2>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <span className="w-5 h-5 rounded-full border-2 border-[#E8E5DF] border-t-[#C96442] animate-spin" />
        </div>
      ) : events.length === 0 ? (
        <div className="bg-white border border-[#E8E5DF] rounded-xl p-10 text-center shadow-sm">
          <p className="text-sm text-[#8B8982]">No drift alerts recorded yet.</p>
        </div>
      ) : (
        <div className="bg-white border border-[#E8E5DF] rounded-xl overflow-hidden shadow-sm">
          <div className="divide-y divide-[#E8E5DF]">
            {events.map((evt) => {
              const barWidth = Math.min(evt.psi * 100, 100);
              return (
                <div key={evt.id} className="flex items-center gap-4 px-5 py-3 text-xs">
                  <span className="text-[#8B8982] font-mono text-[10px] min-w-[70px] shrink-0">
                    {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : ""}
                  </span>
                  <span className="text-[#8B8982] font-mono text-[10px] min-w-[80px] shrink-0">
                    {evt.job_id.slice(0, 8)}
                  </span>
                  <span className="text-[#1C1B19] min-w-[80px] shrink-0">
                    {evt.feature}
                  </span>
                  <div className="flex-1 h-2 rounded-full bg-[#F0EDE8] overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{
                        width: `${Math.max(barWidth, 2)}%`,
                        background: psiColor(evt.psi),
                      }}
                    />
                  </div>
                  <span
                    className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold min-w-[55px] text-center shrink-0"
                    style={{
                      background: psiColor(evt.psi) + "18",
                      color: psiColor(evt.psi),
                    }}
                  >
                    {evt.psi.toFixed(3)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="mt-6 p-4 bg-white border border-[#E8E5DF] rounded-xl text-xs text-[#8B8982] leading-relaxed shadow-sm">
        <strong className="text-[#1C1B19]">PSI Thresholds</strong>
        <br />
        <span className="text-[#10b981]">&lt; 0.1</span> No drift &mdash;
        <span className="text-[#f59e0b]"> 0.1 &ndash; 0.2</span> Moderate drift &mdash;
        <span className="text-[#f43f5e]"> &gt; 0.2</span> Significant drift &mdash;
        triggers automatic retrain via Scout.
      </div>
    </div>
  );
}
