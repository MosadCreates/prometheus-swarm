"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "./AuthProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { Moon, Sun } from "lucide-react";

export default function NavUserMenu() {
  const { user, loading, logout } = useAuth();
  const { theme, toggle } = useTheme();
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
      <Link href="/login" className="btn-outline text-xs py-1.5 px-4 no-underline">
        Sign in
      </Link>
    );
  }

  const initial = (user.name || user.email)[0].toUpperCase();

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="w-8 h-8 rounded-full bg-[var(--color-primary)] text-white text-sm font-semibold flex items-center justify-center hover:opacity-90 transition-opacity cursor-pointer border-none"
        title={user.name || user.email}
      >
        {initial}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-52 bg-[var(--color-surface-elevated)] border border-[var(--color-border)] rounded-[var(--radius-lg)] shadow-lg py-1 animate-fade-in z-50">
          <div className="px-4 py-2.5 border-b border-[var(--color-border)]">
            <div className="text-sm font-medium text-[var(--color-text-primary)] truncate">{user.name}</div>
            <div className="text-xs text-[var(--color-text-muted)] truncate">{user.email}</div>
          </div>
          <Link
            href="/dashboard"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-colors no-underline"
          >
            Dashboard
          </Link>
          <Link
            href="/feed"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-colors no-underline"
          >
            Live Feed
          </Link>
          <Link
            href="/jobs"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-colors no-underline"
          >
            Job History
          </Link>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center px-4 py-2 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-colors no-underline"
          >
            Settings
          </Link>
          <div className="border-t border-[var(--color-border)] mt-1 pt-1">
            <button
              onClick={() => { toggle(); setOpen(false); }}
              className="w-full flex items-center gap-3 px-4 py-2 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-colors bg-transparent border-none cursor-pointer"
            >
              {theme === 'light' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
              {theme === 'light' ? 'Dark mode' : 'Light mode'}
            </button>
            <button
              onClick={() => { setOpen(false); logout(); }}
              className="w-full text-left px-4 py-2 text-sm text-[var(--color-error)] hover:bg-[var(--color-border-light)] transition-colors bg-transparent border-none cursor-pointer"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
