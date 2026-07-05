'use client';

import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { cn } from '@/shared/utils/cn';

interface AppShellProps {
  children: ReactNode;
  className?: string;
}

export function AppShell({ children, className }: AppShellProps) {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <Sidebar />
      <div
        className={cn(
          'ml-[var(--sidebar-width)] min-h-screen flex flex-col',
          'transition-all duration-[var(--duration-slow)] ease-[var(--easing-in-out)]',
          className,
        )}
      >
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
