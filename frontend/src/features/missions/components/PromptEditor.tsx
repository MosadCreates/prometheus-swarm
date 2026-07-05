'use client';

import { useRef, useEffect } from 'react';

interface PromptEditorProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

export function PromptEditor({ value, onChange, placeholder }: PromptEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 320) + 'px';
    }
  }, [value]);

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || "Describe your mission in detail..."}
        className="w-full min-h-[160px] max-h-[320px] resize-none rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-cyan)] focus:ring-2 focus:ring-[var(--color-cyan)]/10 transition-all outline-none"
      />
      <div className="absolute bottom-3 right-3 text-[11px] text-[var(--color-text-muted)]">
        {value.length} chars
      </div>
    </div>
  );
}
