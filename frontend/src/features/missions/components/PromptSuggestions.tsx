'use client';

import { Sparkles } from 'lucide-react';

interface PromptSuggestionsProps {
  suggestions: string[];
  onSelect: (s: string) => void;
}

export function PromptSuggestions({ suggestions, onSelect }: PromptSuggestionsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      <Sparkles className="w-3.5 h-3.5 text-[var(--color-cyan)] mt-0.5" />
      {suggestions.map((s) => (
        <button
          key={s}
          onClick={() => onSelect(s)}
          className="text-xs px-3 py-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] hover:border-[var(--color-cyan)]/30 hover:text-[var(--color-text-primary)] transition-all"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
