'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/shared/utils/cn';
import { PipelineRail } from '@/shared/layout/PipelineRail';
import { PlusCircle, List, Activity, ChevronLeft, ChevronRight } from 'lucide-react';

const utilityLinks = [
  { href: '/submit', label: 'New Problem', icon: PlusCircle },
  { href: '/jobs', label: 'Jobs', icon: List },
  { href: '/drift', label: 'Drift Monitor', icon: Activity },
];

const mockPipelineState = {
  completed: ['scout', 'forge'],
  active: 'furnace' as string | null,
};

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-full flex flex-col bg-[var(--color-bg)] border-r border-[var(--color-border)]',
        'transition-all duration-[var(--duration-slow)] ease-[var(--easing-in-out)]',
        collapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]',
      )}
    >
      {/* Logo */}
      <div className={cn('flex items-center border-b border-[var(--color-border)]', collapsed ? 'justify-center h-12' : 'h-12 px-4')}>
        <Link href="/dashboard" className="flex items-center gap-2.5 no-underline">
          <div className="w-6 h-6 rounded-[var(--radius-sm)] bg-[var(--color-accent)] flex items-center justify-center">
            <span className="text-[10px] font-bold text-white">P</span>
          </div>
          {!collapsed && (
            <span className="text-xs font-semibold text-[var(--color-text-primary)] tracking-tight">Prometheus</span>
          )}
        </Link>
      </div>

      {/* Pipeline rail */}
      <div className={cn('flex-shrink-0', collapsed ? 'py-4 flex justify-center' : 'py-5 px-4')}>
        <PipelineRail
          state={mockPipelineState}
          orientation="vertical"
          showLabels={!collapsed}
        />
      </div>

      {/* Separator */}
      <div className="hairline mx-4" />

      {/* Utility links */}
      <nav className="flex-1 overflow-y-auto py-3">
        <ul className={cn('flex flex-col gap-0.5', collapsed ? 'px-3' : 'px-3')}>
          {utilityLinks.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-[var(--radius-sm)] text-xs font-medium transition-all duration-[var(--duration-fast)]',
                    'hover:bg-[var(--color-surface)]',
                    active
                      ? 'bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]',
                    collapsed ? 'justify-center h-9 w-9' : 'px-3 h-9',
                  )}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-[var(--color-border)] p-2">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            'flex items-center justify-center w-full h-8 rounded-[var(--radius-sm)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-surface)] transition-all',
          )}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          {!collapsed && <span className="text-[10px] ml-2">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
