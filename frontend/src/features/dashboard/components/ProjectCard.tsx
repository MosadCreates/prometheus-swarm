'use client';

import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { cn } from '@/shared/utils/cn';
import { Badge } from '@/shared/ui';
import { projectStatusStyles } from '../constants/mock';

interface Project {
  id: string;
  name: string;
  description: string;
  lastUpdated: string;
  status: string;
  missions: number;
  color: string;
}

export function ProjectCard({ project }: { project: Project }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="block rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-4 hover:shadow-md hover:border-[var(--color-border)] transition-all group no-underline"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2.5">
          <div className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: project.color }} />
          <span className="text-sm font-medium text-[var(--color-text-primary)]">{project.name}</span>
        </div>
        <Badge variant={project.status as any} size="sm">
          {project.status}
        </Badge>
      </div>
      <p className="text-xs text-[var(--color-text-secondary)] mb-3 line-clamp-2">{project.description}</p>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[var(--color-text-muted)]">{project.missions} missions · {project.lastUpdated}</span>
        <ArrowUpRight className="w-3.5 h-3.5 text-[var(--color-text-muted)] group-hover:text-[var(--color-primary)] transition-colors" />
      </div>
    </Link>
  );
}
