"use client";

import { useEffect, useState } from "react";

interface DriftEvent {
  id: string;
  job_id: string;
  psi: number;
  feature: string;
  timestamp: string;
}

function psiGradient(psi: number): string {
  const pct = Math.min(psi / 0.3, 1);
  const r = Math.round(22 + (229 - 22) * pct);
  const g = Math.round(195 + (72 - 195) * pct);
  const b = Math.round(199 + (77 - 199) * pct);
  return `rgb(${r}, ${g}, ${b})`;
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

  // Aggregate by feature, take max PSI, sort descending
  const featureMap = new Map<string, DriftEvent>();
  for (const evt of events) {
    const existing = featureMap.get(evt.feature);
    if (!existing || evt.psi > existing.psi) {
      featureMap.set(evt.feature, evt);
    }
  }
  const features = Array.from(featureMap.values()).sort((a, b) => b.psi - a.psi);

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="text-sm font-semibold text-[var(--color-text-primary)] mb-6">PSI Drift Monitor</h1>

      {/* Status strip */}
      <div className="flex items-center gap-3 px-4 py-3 border border-[var(--color-border)] bg-[var(--color-surface)] mb-6">
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: hasActiveDrift ? "var(--color-alert)" : "var(--color-cyan)" }}
        />
        <span
          className="text-xs font-mono font-semibold"
          style={{ color: hasActiveDrift ? "var(--color-alert)" : "var(--color-cyan)" }}
        >
          {hasActiveDrift ? "Drift Detected" : "Stable"}
        </span>
        <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
          {events.length} alerts · {features.length} features
        </span>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <span className="w-4 h-4 rounded-full border border-[var(--color-border)] border-t-[var(--color-accent)] animate-spin" />
        </div>
      )}

      {/* Empty */}
      {!loading && features.length === 0 && (
        <div className="text-center py-16 text-xs text-[var(--color-text-muted)] font-mono">
          No drift data recorded yet.
        </div>
      )}

      {/* Feature gauges */}
      {!loading && features.length > 0 && (
        <div className="border border-[var(--color-border)]">
          {/* Header */}
          <div className="flex items-center gap-4 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[120px] uppercase tracking-wider">Feature</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] flex-1 uppercase tracking-wider">PSI Gauge</span>
            <span className="text-[10px] font-mono text-[var(--color-text-muted)] w-[80px] uppercase tracking-wider text-right">PSI Value</span>
          </div>

          {/* Rows */}
          <div className="divide-y divide-[var(--color-border)]">
            {features.map((evt) => (
              <div key={evt.feature} className="flex items-center gap-4 px-4 py-3 hover:bg-[var(--color-surface)] transition-colors">
                <span className="text-xs text-[var(--color-text-primary)] font-mono w-[120px] shrink-0 truncate">
                  {evt.feature}
                </span>

                {/* Gauge bar — green → amber → red gradient */}
                <div className="flex-1 h-2 rounded-[var(--radius-sm)] bg-[var(--color-border)] overflow-hidden">
                  <div
                    className="h-full rounded-[var(--radius-sm)] transition-all duration-300"
                    style={{
                      width: `${Math.min(evt.psi * 100, 100)}%`,
                      backgroundColor: psiGradient(evt.psi),
                    }}
                  />
                </div>

                <span
                  className="text-xs font-mono font-semibold w-[80px] shrink-0 text-right"
                  style={{ color: psiGradient(evt.psi) }}
                >
                  {evt.psi.toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Threshold legend */}
      <div className="mt-6 px-4 py-3 border border-[var(--color-border)] bg-[var(--color-surface)] text-[10px] font-mono text-[var(--color-text-muted)] leading-relaxed">
        <strong className="text-[var(--color-text-primary)]">PSI Thresholds</strong>
        <br />
        <span style={{ color: "#3fd3c7" }}>&lt; 0.1</span> No drift &mdash;
        <span style={{ color: "#e8a33d" }}> 0.1 &ndash; 0.2</span> Moderate &mdash;
        <span style={{ color: "#e5484d" }}> &gt; 0.2</span> Significant &mdash;
        triggers automatic retrain via Scout.
      </div>
    </div>
  );
}
