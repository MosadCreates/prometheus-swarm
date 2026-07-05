"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "./AuthProvider";

export default function NavUserMenu() {
  const { user, loading, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  if (loading) return null;

  if (!user) {
    return (
      <Link href="/login" className="text-xs font-mono font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors no-underline px-3 py-1.5 border border-[var(--color-border)] rounded-[var(--radius-sm)]">
        Sign in
      </Link>
    );
  }

  const initial = (user.name || user.email)[0].toUpperCase();

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="w-7 h-7 rounded-[var(--radius-sm)] bg-[var(--color-accent)] text-white text-xs font-bold flex items-center justify-center hover:opacity-90 transition-opacity cursor-pointer border-none"
        title={user.name || user.email}
      >
        {initial}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-52 bg-[var(--color-bg)] border border-[var(--color-border)] shadow-lg py-1 z-50">
          <div className="px-4 py-2.5 border-b border-[var(--color-border)]">
            <div className="text-xs font-medium text-[var(--color-text-primary)] truncate">{user.name}</div>
            <div className="text-[10px] font-mono text-[var(--color-text-muted)] truncate">{user.email}</div>
          </div>
          <Link
            href="/dashboard"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-xs text-[var(--color-text-primary)] hover:bg-[var(--color-surface)] transition-colors no-underline"
          >
            Dashboard
          </Link>
          <Link
            href="/feed"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-xs text-[var(--color-text-primary)] hover:bg-[var(--color-surface)] transition-colors no-underline"
          >
            Live Feed
          </Link>
          <Link
            href="/jobs"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-xs text-[var(--color-text-primary)] hover:bg-[var(--color-surface)] transition-colors no-underline"
          >
            Job History
          </Link>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-xs text-[var(--color-text-primary)] hover:bg-[var(--color-surface)] transition-colors no-underline"
          >
            Settings
          </Link>
          <div className="border-t border-[var(--color-border)] mt-1 pt-1">
            <button
              onClick={() => { setOpen(false); logout(); }}
              className="w-full text-left px-4 py-2 text-xs text-[var(--color-alert)] hover:bg-[var(--color-surface)] transition-colors bg-transparent border-none cursor-pointer"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
