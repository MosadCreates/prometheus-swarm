"use client";

import { useState, useRef, type DragEvent } from "react";
import { AppShell } from "@/shared/layouts/AppShell";
import { Upload, Terminal } from "lucide-react";

export default function SubmitPage() {
  const [prompt, setPrompt] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) setFileName(file.name);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setFileName(file.name);
  };

  const handleSubmit = () => {
    if (!prompt.trim()) {
      setError("Describe what you want the swarm to build.");
      return;
    }
    setError(null);
    // TODO: submit to orchestrator
  };

  return (
    <AppShell>
      <div className="max-w-2xl mx-auto px-6 py-10">
        <div className="flex items-center gap-3 mb-8">
          <Terminal className="w-4 h-4 text-[var(--color-accent)]" />
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">New Problem</h1>
        </div>

        {/* Problem description */}
        <div className="mb-5">
          <label className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-2 block">
            Problem Description
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Train a classifier on the Titanic dataset to predict survival from passenger features like age, sex, and class."
            rows={6}
            className="w-full bg-[var(--color-surface)] border border-[var(--color-border)] rounded-[var(--radius-sm)] px-4 py-3 text-xs text-[var(--color-text-primary)] font-mono placeholder-[var(--color-text-muted)] outline-none transition-colors resize-none focus:border-[var(--color-accent)]"
            style={{ fontSize: "12px", lineHeight: "1.6" }}
          />
        </div>

        {/* File dropzone */}
        <div className="mb-6">
          <label className="text-[10px] font-mono text-[var(--color-text-muted)] uppercase tracking-wider mb-2 block">
            Dataset (optional)
          </label>
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-[var(--radius-sm)] px-5 py-8 text-center cursor-pointer transition-colors ${
              dragOver
                ? "border-[var(--color-warning)] bg-[var(--color-warning)]/5"
                : "border-[var(--color-border)] hover:border-[var(--color-text-muted)]"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              className="hidden"
            />
            <Upload className="w-5 h-5 text-[var(--color-text-muted)] mx-auto mb-2" />
            {fileName ? (
              <p className="text-xs text-[var(--color-text-secondary)] font-mono">{fileName}</p>
            ) : (
              <>
                <p className="text-xs text-[var(--color-text-secondary)] mb-1">Drop a CSV or dataset here</p>
                <p className="text-[10px] text-[var(--color-text-muted)] font-mono">or click to browse</p>
              </>
            )}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 px-3 py-2 border border-[var(--color-alert)]/30 bg-[var(--color-alert)]/5">
            <p className="text-xs text-[var(--color-alert)] font-mono">{error}</p>
          </div>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={!prompt.trim()}
          className="w-full h-10 rounded-[var(--radius-sm)] bg-[var(--color-accent)] text-white text-xs font-semibold font-mono hover:bg-[var(--color-accent-hover)] disabled:opacity-30 disabled:pointer-events-none transition-all flex items-center justify-center gap-2"
        >
          Start the swarm
        </button>
      </div>
    </AppShell>
  );
}
