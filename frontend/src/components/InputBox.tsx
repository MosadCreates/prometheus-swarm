"use client";

import { useState, FormEvent } from "react";
import { FileUpload } from "@/components/ui/file-upload";
import { PlaceholdersAndVanishInput } from "@/components/ui/placeholders-and-vanish-input";

interface InputBoxProps {
  onStartJob: (description: string, file: File | null) => Promise<void>;
  disabled: boolean;
}

const placeholders = [
  "Describe your ML problem...",
  "Predict Titanic survival based on age, sex, and ticket class",
  "Classify Iris flower species by petal and sepal measurements",
  "Forecast monthly sales for a retail chain",
  "Detect fraudulent credit card transactions",
];

export default function InputBox({ onStartJob, disabled }: InputBoxProps) {
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!description.trim()) return;
    await onStartJob(description.trim(), file);
    setDescription("");
    setFile(null);
  }

  return (
    <div className="input-area px-4 py-2">
      <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex items-center gap-2">
        <div className="flex-1">
          <PlaceholdersAndVanishInput
            placeholders={placeholders}
            value={description}
            onChange={setDescription}
            onSubmit={handleSubmit}
            disabled={disabled}
          />
        </div>

        <FileUpload
          onChange={(files) => setFile(files[0] || null)}
        />

        <button
          type="submit"
          disabled={disabled || !description.trim()}
          className="flex items-center justify-center w-10 h-10 rounded-xl bg-[#C96442] text-white hover:bg-[#B85535] transition-all disabled:opacity-50 cursor-pointer shrink-0"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </form>
    </div>
  );
}
