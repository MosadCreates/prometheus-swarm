"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";

const agents = [
  { name: "Scout", role: "The Perceiver", color: "var(--color-agent-scout)" },
  { name: "Forge", role: "The Architect", color: "var(--color-agent-forge)" },
  { name: "Furnace", role: "The Trainer", color: "var(--color-agent-furnace)" },
  { name: "Dissect", role: "The Debugger", color: "var(--color-agent-dissect)" },
  { name: "Arbiter", role: "The Critic", color: "var(--color-agent-arbiter)" },
  { name: "Harbor", role: "The Deployer", color: "var(--color-agent-harbor)" },
];

const capabilities = [
  "Tabular classification", "Tabular regression",
  "Text classification", "Image classification",
  "LightGBM", "XGBoost", "TabNet", "DistilBERT", "EfficientNet",
  "Optuna hyperparameter tuning", "Class imbalance handling",
  "GPU training", "ONNX export", "REST API deployment",
  "Drift monitoring", "Self-healing training pipelines",
];

export default function Home() {
  const { user, loading } = useAuth();
  return (
    <div className="max-w-3xl mx-auto px-6">
      <section className="pt-32 pb-16">
        <div className="flex items-center gap-2 mb-6">
          <span className="w-2 h-2 rounded-full bg-[var(--color-accent)]" />
          <span className="text-xs font-medium text-[var(--color-text-muted)] tracking-widest uppercase">
            Prometheus Swarm
          </span>
        </div>
        <h1 className="text-5xl sm:text-6xl leading-[1.1] tracking-tight text-[var(--color-text-primary)] mb-5 font-bold">
          You describe the task.
          <br />
          <span className="italic font-normal">The swarm does the rest.</span>
        </h1>
        <p className="text-base text-[var(--color-text-secondary)] leading-relaxed max-w-xl mb-8">
          An autonomous multi-agent system that accepts a raw natural-language description
          of a machine-learning problem and returns&mdash;without any human intervention&mdash;a
          fully trained, evaluated, and live-served model endpoint.
        </p>
        <div className="flex items-center gap-3">
          {!loading && (
            <Link href={user ? "/dashboard" : "/login"} className="btn-accent">
              {user ? "Dashboard" : "New Problem"}
            </Link>
          )}
          <Link href="/feed" className="btn-outline">
            Live feed
          </Link>
        </div>
      </section>

      <div className="section-divider" />

      <section className="py-8">
        <h2 className="text-2xl text-[var(--color-text-primary)] mb-2 font-bold">How it works</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-10 max-w-lg">
          Six specialized AI agents. Each an independent process with its own tools and memory.
          They communicate exclusively through a Redis message bus&mdash;no agent calls another directly.
        </p>
        <div className="space-y-0">
          {agents.map((agent, i) => (
            <div key={agent.name} className="flex items-start gap-4 py-4 border-t border-[var(--color-border)] first:border-t-0">
              <div className="flex items-center gap-3 min-w-[140px]">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: agent.color }} />
                <div>
                  <div className="text-sm font-semibold text-[var(--color-text-primary)]">{agent.name}</div>
                  <div className="text-xs text-[var(--color-text-muted)]">{agent.role}</div>
                </div>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
                {i === 0 && "Parses the problem description, runs EDA, writes the mission brief."}
                {i === 1 && "Selects architecture, writes the training script, defines the search space."}
                {i === 2 && "Launches the training container, monitors loss, streams epoch metrics."}
                {i === 3 && "Catches training crashes, classifies errors, applies patches autonomously."}
                {i === 4 && "Evaluates the model, computes metrics, decides pass/retry/escalate."}
                {i === 5 && "Exports to ONNX, builds a FastAPI endpoint, monitors for drift."}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div className="section-divider" />

      <section className="py-8">
        <h2 className="text-2xl text-[var(--color-text-primary)] mb-2 font-bold">Capabilities</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-8 max-w-lg">
          What the swarm can build, train, and serve.
        </p>
        <div className="flex flex-wrap gap-2">
          {capabilities.map((cap) => (
            <span key={cap} className="tag">{cap}</span>
          ))}
        </div>
      </section>

      <div className="section-divider" />

      <section className="py-8 mb-24">
        <h2 className="text-2xl text-[var(--color-text-primary)] mb-2 font-bold">Research</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-10 max-w-lg">
          Development phases, from foundation to production.
        </p>
        <div className="relative pl-8">
          <div className="absolute left-[7px] top-2 bottom-0 w-px bg-[var(--color-border)]" />
            {[
    { phase: "Phase 0", title: "Foundation", date: "2026 Q1", desc: "Redis, Docker, Claude API, ChromaDB. Four infrastructure components communicating via message bus." },
    { phase: "Phase 1", title: "Scout + Forge + Furnace", date: "2026 Q2", desc: "Titanic end-to-end: raw problem description to trained LightGBM model." },
    { phase: "Phase 2", title: "Dissect + Arbiter + Harbor", date: "2026 Q2", desc: "Error recovery, evaluation, and deployment. Auto-patches 5 injected errors." },
    { phase: "Phase 3", title: "Memory + Hardening", date: "2026 Q3", desc: "ChromaDB long-term memory. Dissect learns from history. All 108 tests passing." },
    { phase: "Phase 4", title: "Research Experiment", date: "2026 Q3", desc: "50-problem benchmark. Mann-Whitney U test. Paper submission to MSR / ASE 2026." },
  ].map((item) => (
            <div key={item.phase} className="relative pb-10 last:pb-0">
              <div className="absolute -left-8 top-1.5 w-[15px] h-[15px] rounded-full border-2 border-[var(--color-accent)] bg-[var(--color-bg)]" />
              <div className="text-xs text-[var(--color-accent)] font-semibold mb-1 tracking-wider uppercase">{item.phase}</div>
              <div className="text-sm font-semibold text-[var(--color-text-primary)] mb-0.5">
                {item.title}
                <span className="text-[var(--color-text-muted)] font-normal ml-2 text-xs">{item.date}</span>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
