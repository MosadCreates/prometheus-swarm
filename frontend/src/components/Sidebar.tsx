"use client";

import { useEffect, useState } from "react";
import { useAuth } from "./AuthProvider";
import { supabase } from "@/lib/supabase";

interface ChatSession {
  id: string;
  job_id: string;
  problem_description: string;
  status: string;
  created_at: string;
}

const STATUS_DOTS: Record<string, string> = {
  completed: "#10b981", COMPLETED: "#10b981", pass: "#10b981",
  running: "#f59e0b", QUEUED: "#94a3b8", ESCALATED: "#f43f5e",
  failed: "#f43f5e", escalated: "#f43f5e",
};

export default function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { user, logout } = useAuth();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    (async () => {
      const { data } = await supabase
        .from("chat_sessions")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(30);
      if (data) setSessions(data);
    })();
  }, [user]);

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="flex items-center justify-center h-14 border-b border-[#E8E5DF]">
        <button onClick={onToggle} className="text-[#8B8982] hover:text-[#1C1B19] transition-colors bg-transparent border-none cursor-pointer p-1 text-lg">
          ☰
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
            {sessions.length === 0 && (
              <div className="text-center py-8 text-xs text-[#8B8982]">No chat history yet</div>
            )}
            {sessions.map((s) => (
              <a
                key={s.id}
                href={`/jobs/${encodeURIComponent(s.job_id)}`}
                onClick={() => setActiveId(s.id)}
                className={`sidebar-item flex items-center gap-2.5 px-3 py-2 rounded-lg no-underline ${
                  activeId === s.id ? "active" : ""
                }`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: STATUS_DOTS[s.status || ""] || "#94a3b8" }}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-[#1C1B19] truncate font-medium">
                    {s.problem_description?.slice(0, 40) || "Untitled"}
                  </div>
                  <div className="text-[10px] text-[#8B8982] mt-0.5">
                    {s.created_at ? new Date(s.created_at).toLocaleDateString() : ""}
                    <span className="ml-1.5 capitalize">{s.status?.toLowerCase() || "unknown"}</span>
                  </div>
                </div>
              </a>
            ))}
          </div>

          <div className="border-t border-[#E8E5DF] px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-[#1C1B19] truncate">{user?.name || "User"}</div>
                <div className="text-[10px] text-[#8B8982] truncate">{user?.email || ""}</div>
              </div>
              <button onClick={logout} className="text-xs text-[#8B8982] hover:text-[#C96442] transition-colors bg-transparent border-none cursor-pointer shrink-0 ml-2">
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
