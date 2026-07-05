"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface PlaceholdersAndVanishInputProps {
  placeholders: string[];
  value: string;
  onChange: (value: string) => void;
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
  disabled?: boolean;
}

export function PlaceholdersAndVanishInput({
  placeholders,
  value,
  onChange,
  onSubmit,
  disabled,
}: PlaceholdersAndVanishInputProps) {
  const [currentPlaceholder, setCurrentPlaceholder] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentPlaceholder((prev) => (prev + 1) % placeholders.length);
    }, 3000);
    return () => clearInterval(interval);
  }, [placeholders.length]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const form = (e.target as HTMLElement).closest("form");
      if (form) form.requestSubmit();
    }
  }, []);

  return (
    <div className="relative w-full">
      <div className="relative flex items-center w-full rounded-xl border border-[#E8E5DF] bg-white/80 transition-colors focus-within:border-[#C96442]">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          className="w-full px-4 py-3 bg-transparent outline-none text-sm text-[#1C1B19] placeholder-transparent disabled:opacity-50"
        />
        <AnimatePresence mode="wait">
          {!value && (
            <motion.span
              key={currentPlaceholder}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
              className="absolute left-4 text-sm text-[#8B8982] pointer-events-none truncate max-w-[calc(100%-3rem)]"
            >
              {placeholders[currentPlaceholder]}
            </motion.span>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
