'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/shared/utils/cn';
import {
  LayoutDashboard,
  FolderKanban,
  Rocket,
  Brain,
  Database,
  GraduationCap,
  Globe,
  Settings,
  Search,
  ChevronLeft,
  ChevronRight,
  History,
  Clock,
  Box,
} from 'lucide-react';

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/projects', label: 'Projects', icon: FolderKanban },
  { href: '/missions', label: 'Missions', icon: Rocket },
  { href: '/models', label: 'Models', icon: Brain },
  { href: '/datasets', label: 'Datasets', icon: Database },
  { href: '/training', label: 'Training', icon: GraduationCap },
  { href: '/deployments', label: 'Deployments', icon: Globe },
  { href: '/settings', label: 'Settings', icon: Settings },
] as const;

const mockRecentMissions = [
  { name: 'Titanic classification', status: 'completed' as const, time: '2h ago' },
  { name: 'Image segmentation', status: 'running' as const, time: 'now' },
  { name: 'Sentiment analysis', status: 'failed' as const, time: '1d ago' },
];

const mockRecentProjects = [
  { name: 'Kaggle Titanic', color: '#2563eb', lastOpened: '2h ago' },
  { name: 'NLP Pipeline', color: '#7c3aed', lastOpened: '1d ago' },
  { name: 'Vision Demo', color: '#059669', lastOpened: '3d ago' },
];

const statusColors = {
  completed: 'bg-[var(--color-success)]',
  running: 'bg-[var(--color-primary)]',
  failed: 'bg-[var(--color-error)]',
  queued: 'bg-[var(--color-warning)]',
};

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 h-full flex flex-col bg-[var(--color-surface)] border-r border-[var(--color-border)]',
        'transition-all duration-[var(--duration-slow)] ease-[var(--easing-in-out)]',
        collapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]',
      )}
    >
      {/* Header */}
      <div className={cn('flex items-center h-14 border-b border-[var(--color-border)] px-4', collapsed && 'justify-center px-0')}>
        {!collapsed && (
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-[var(--radius-md)] bg-[var(--color-primary)] flex items-center justify-center">
              <span className="text-xs font-bold text-white">P</span>
            </div>
            <span className="text-sm font-semibold text-[var(--color-text-primary)]">Prometheus</span>
          </Link>
        )}
        {collapsed && (
          <Link href="/dashboard">
            <div className="w-7 h-7 rounded-[var(--radius-md)] bg-[var(--color-primary)] flex items-center justify-center">
              <span className="text-xs font-bold text-white">P</span>
            </div>
          </Link>
        )}
      </div>

      {/* Search */}
      {!collapsed && (
        <button className="flex items-center gap-2 mx-3 mt-3 h-9 px-3 rounded-[var(--radius-md)] border border-[var(--color-border)] text-xs text-[var(--color-text-muted)] hover:border-[var(--color-primary)] transition-colors">
          <Search className="w-3.5 h-3.5" />
          <span className="flex-1 text-left">Search...</span>
          <kbd className="text-[10px] text-[var(--color-text-muted)] bg-[var(--color-border-light)] px-1.5 py-0.5 rounded">Ctrl+K</kbd>
        </button>
      )}

      {/* Navigation */}
      <nav className={cn('flex-1 overflow-y-auto py-3', collapsed ? 'px-2' : 'px-3')}>
        <ul className="flex flex-col gap-0.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || pathname.startsWith(item.href + '/');
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-[var(--radius-md)] text-sm font-medium transition-all duration-[var(--duration-fast)]',
                    'hover:bg-[var(--color-border-light)]',
                    active
                      ? 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]',
                    collapsed ? 'justify-center h-10 w-10' : 'px-3 h-9',
                  )}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                  {active && !collapsed && (
                    <span className="ml-auto w-1.5 h-1.5 rounded-full bg-[var(--color-primary)]" />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>

        {/* Recent Missions */}
        {!collapsed && (
          <div className="mt-6">
            <div className="flex items-center gap-1.5 px-3 mb-2">
              <History className="w-3 h-3 text-[var(--color-text-muted)]" />
              <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Recent</span>
            </div>
            <ul className="flex flex-col gap-0.5">
              {mockRecentMissions.map((mission) => (
                <li key={mission.name}>
                  <Link
                    href="/missions"
                    className="flex items-center gap-2.5 px-3 py-1.5 rounded-[var(--radius-md)] text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)] hover:text-[var(--color-text-primary)] transition-colors"
                  >
                    <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', statusColors[mission.status])} />
                    <span className="truncate flex-1">{mission.name}</span>
                    <span className="text-[10px] text-[var(--color-text-muted)]">{mission.time}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Recent Projects */}
        {!collapsed && (
          <div className="mt-4">
            <div className="flex items-center gap-1.5 px-3 mb-2">
              <Clock className="w-3 h-3 text-[var(--color-text-muted)]" />
              <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">Projects</span>
            </div>
            <ul className="flex flex-col gap-0.5">
              {mockRecentProjects.map((project) => (
                <li key={project.name}>
                  <Link
                    href="/projects"
                    className="flex items-center gap-2.5 px-3 py-1.5 rounded-[var(--radius-md)] text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-border-light)] hover:text-[var(--color-text-primary)] transition-colors"
                  >
                    <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: project.color }} />
                    <span className="truncate flex-1">{project.name}</span>
                    <span className="text-[10px] text-[var(--color-text-muted)]">{project.lastOpened}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-[var(--color-border)] p-2">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            'flex items-center justify-center w-full h-8 rounded-[var(--radius-md)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-border-light)] transition-all',
          )}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          {!collapsed && <span className="text-xs ml-2">Collapse</span>}
        </button>
      </div>
    </aside>
  );
}
