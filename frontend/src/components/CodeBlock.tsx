"use client";

import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

interface CodeBlockProps {
  code: string;
  language?: string;
  fileName?: string;
}

export default function CodeBlock({ code, language = "python", fileName }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  }

  return (
    <div className="rounded-xl overflow-hidden border border-[#E8E5DF] bg-white">
      {fileName && (
        <div className="flex items-center justify-between px-4 py-2 bg-[#F7F6F3] border-b border-[#E8E5DF]">
          <span className="text-[11px] font-mono text-[#8B8982]">{fileName}</span>
          <button
            onClick={handleCopy}
            className="text-[11px] text-[#8B8982] hover:text-[#1C1B19] transition-colors bg-transparent border-none cursor-pointer"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      )}
      <SyntaxHighlighter
        language={language}
        style={oneLight}
        customStyle={{ margin: 0, padding: "1rem", fontSize: "12px", lineHeight: "1.6" }}
        showLineNumbers
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
