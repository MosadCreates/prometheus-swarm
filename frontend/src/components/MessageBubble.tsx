"use client";

interface MessageBubbleProps {
  text: string;
  fileName?: string;
}

export default function MessageBubble({ text, fileName }: MessageBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] bg-[#C96442] text-white rounded-2xl rounded-br-md px-4 py-2.5 shadow-sm">
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{text}</p>
        {fileName && (
          <div className="flex items-center gap-1.5 mt-1.5 text-[11px] text-white/80">
            <span>📎</span>
            <span>{fileName}</span>
          </div>
        )}
      </div>
    </div>
  );
}
