'use client';

import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';

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
      className="block px-4 py-3 hover:bg-[var(--color-surface)] transition-colors group no-underline"
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-2 h-2 rounded-[2px] shrink-0" style={{ backgroundColor: project.color }} />
        <span className="text-xs text-[var(--color-text-primary)]">{project.name}</span>
      </div>
      <p className="text-[10px] font-mono text-[var(--color-text-secondary)] mb-2 line-clamp-2">{project.description}</p>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono text-[var(--color-text-muted)]">{project.missions} missions · {project.lastUpdated}</span>
        <ArrowUpRight className="w-3 h-3 text-[var(--color-text-muted)] group-hover:text-[var(--color-accent)] transition-colors" />
      </div>
    </Link>
  );
}
