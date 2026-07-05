"use client";

import { useEffect, useRef, useState } from "react";
import AgentCard from "./AgentCard";
import MessageBubble from "./MessageBubble";

interface StreamEvent {
  stream: string;
  id: string;
  data: Record<string, string>;
}

interface ChatMessage {
  type: "user" | "agent";
  text?: string;
  fileName?: string;
  event?: StreamEvent;
  timestamp: number;
}

interface ChatViewProps {
  jobId: string | null;
  userMessage: string;
  userFileName?: string;
}

export default function ChatView({ jobId, userMessage, userFileName }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevJobRef = useRef<string | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (jobId && jobId !== prevJobRef.current) {
      prevJobRef.current = jobId;
      setMessages([]);

      setMessages([{ type: "user", text: userMessage, fileName: userFileName, timestamp: Date.now() }]);

      const evtSource = new EventSource(`/api/feed?job_id=${jobId}`);

      evtSource.onopen = () => setConnected(true);

      evtSource.onmessage = (e) => {
        try {
          const parsed = JSON.parse(e.data);
          if (parsed.status === "connected") return;
          if (parsed.error) return;

          setMessages((prev) => [
            ...prev,
            {
              type: "agent",
              event: parsed,
              timestamp: Date.now(),
            },
          ]);
        } catch {}
      };

      evtSource.onerror = () => {
        setConnected(false);
      };

      return () => evtSource.close();
    }
  }, [jobId, userMessage, userFileName]);

  if (!jobId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center max-w-sm">
          <div className="flex items-center justify-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-[#C96442]" />
            <span className="text-sm font-semibold text-[#1C1B19]">Prometheus Swarm</span>
          </div>
          <p className="text-sm text-[#8B8982] leading-relaxed">
            Describe your ML problem, upload a dataset, and the swarm will train, evaluate, and deploy — automatically.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-scroll">
      <div className="max-w-3xl mx-auto px-4 space-y-3">
        {messages.map((msg, i) =>
          msg.type === "user" ? (
            <MessageBubble key={i} text={msg.text || ""} fileName={msg.fileName} />
          ) : msg.event ? (
            <AgentCard key={`${msg.event.stream}-${msg.event.id}`} event={msg.event} />
          ) : null
        )}
        <div ref={bottomRef} />
      </div>
      {!connected && messages.length > 1 && (
        <div className="text-center py-2 text-[11px] text-[#f59e0b]">Reconnecting to agent feed...</div>
      )}
    </div>
  );
}
