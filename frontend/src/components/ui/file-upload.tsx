"use client";

import { useCallback, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface FileUploadProps {
  onChange: (files: File[]) => void;
  accept?: string;
}

export function FileUpload({ onChange, accept = ".csv,.xlsx,.xls,.tsv,.json" }: FileUploadProps) {
  const [files, setFiles] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback((newFiles: FileList | File[]) => {
    const fileArray = Array.from(newFiles);
    setFiles(fileArray);
    onChange(fileArray);
  }, [onChange]);

  const removeFile = useCallback((i: number) => {
    const updated = files.filter((_, idx) => idx !== i);
    setFiles(updated);
    onChange(updated);
  }, [files, onChange]);

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => e.target.files && handleFiles(e.target.files)}
        multiple
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex items-center justify-center w-10 h-10 rounded-xl bg-white/80 border border-[#E8E5DF] text-[#8B8982] hover:text-[#1C1B19] hover:border-[#C96442] transition-all cursor-pointer shrink-0"
        title="Upload dataset"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </button>

      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="absolute bottom-full left-0 mb-2 flex flex-wrap gap-1.5"
          >
            {files.map((file, i) => (
              <div
                key={`${file.name}-${i}`}
                className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[#F0EDE8] border border-[#E8E5DF] text-[11px]"
              >
                <span className="max-w-[100px] truncate text-[#1C1B19]">{file.name}</span>
                <button
                  type="button"
                  onClick={() => removeFile(i)}
                  className="text-[#8B8982] hover:text-[#C96442] bg-transparent border-none cursor-pointer p-0 leading-none"
                >
                  ×
                </button>
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
