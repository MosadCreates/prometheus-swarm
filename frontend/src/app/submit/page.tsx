"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";

export default function SubmitPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const form = e.currentTarget;
    const data = new FormData(form);
    const file = data.get("file") as File;

    if (!file || file.size === 0) {
      setError("Please select a dataset file.");
      setSubmitting(false);
      return;
    }

    try {
      const res = await fetch("/api/jobs/submit", { method: "POST", body: data });
      const body = await res.json();
      if (!res.ok) {
        setError(body.error || "Submission failed");
        setSubmitting(false);
        return;
      }
      router.push(`/jobs/${body.job_id}`);
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "16px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>New Problem</h1>
      <p style={{ fontSize: 13, color: "#64748b", marginBottom: 20 }}>
        Describe your ML problem and upload a dataset. The swarm will train, evaluate, and deploy
        a model automatically.
      </p>

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

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div>
          <label
            htmlFor="problem_description"
            style={{ display: "block", fontSize: 13, color: "#94a3b8", marginBottom: 4 }}
          >
            Problem Description *
          </label>
          <textarea
            id="problem_description"
            name="problem_description"
            required
            placeholder='e.g. "Predict which Titanic passengers survived"'
            rows={3}
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 6,
              border: "1px solid #1e1e2e",
              background: "#14141f",
              color: "#e0e0e0",
              fontSize: 13,
              fontFamily: "inherit",
              resize: "vertical",
            }}
          />
        </div>

        <div>
          <label
            htmlFor="file"
            style={{ display: "block", fontSize: 13, color: "#94a3b8", marginBottom: 4 }}
          >
            Dataset File * (CSV, XLSX)
          </label>
          <input
            id="file"
            name="file"
            type="file"
            accept=".csv,.xlsx,.xls,.tsv,.json"
            required
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: 6,
              border: "1px solid #1e1e2e",
              background: "#14141f",
              color: "#e0e0e0",
              fontSize: 13,
            }}
          />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 12,
          }}
        >
          <div>
            <label
              htmlFor="target_column"
              style={{ display: "block", fontSize: 13, color: "#94a3b8", marginBottom: 4 }}
            >
              Target Column (optional)
            </label>
            <input
              id="target_column"
              name="target_column"
              type="text"
              placeholder="e.g. Survived"
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid #1e1e2e",
                background: "#14141f",
                color: "#e0e0e0",
                fontSize: 13,
              }}
            />
          </div>
          <div>
            <label
              htmlFor="max_latency"
              style={{ display: "block", fontSize: 13, color: "#94a3b8", marginBottom: 4 }}
            >
              Max Latency (ms, optional)
            </label>
            <input
              id="max_latency"
              name="max_latency"
              type="number"
              placeholder="e.g. 100"
              style={{
                width: "100%",
                padding: "8px 12px",
                borderRadius: 6,
                border: "1px solid #1e1e2e",
                background: "#14141f",
                color: "#e0e0e0",
                fontSize: 13,
              }}
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={submitting}
          style={{
            padding: "10px 20px",
            borderRadius: 6,
            border: "none",
            background: submitting ? "#334155" : "#3b82f6",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: submitting ? "not-allowed" : "pointer",
            marginTop: 4,
          }}
        >
          {submitting ? "Submitting..." : "Submit Problem"}
        </button>
      </form>

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
        <strong style={{ color: "#94a3b8" }}>What happens next?</strong>
        <br />
        1. Your file is uploaded to the private uploads directory.
        <br />
        2. <strong style={{ color: "#22c55e" }}>Scout</strong> analyzes the dataset and creates a mission brief.
        <br />
        3. <strong style={{ color: "#3b82f6" }}>Forge</strong> selects the best architecture and generates a training script.
        <br />
        4. <strong style={{ color: "#f59e0b" }}>Furnace</strong> trains the model in an isolated Docker sandbox.
        <br />
        5. <strong style={{ color: "#a855f7" }}>Dissect</strong> fixes any training errors automatically.
        <br />
        6. <strong style={{ color: "#06b6d4" }}>Arbiter</strong> evaluates the model and decides if it passes.
        <br />
        7. <strong style={{ color: "#ec4899" }}>Harbor</strong> deploys the model as a live API endpoint.
        <br />
        Watch the live feed at <a href="/feed" style={{ color: "#3b82f6" }}>/feed</a> to track progress.
      </div>
    </div>
  );
}
