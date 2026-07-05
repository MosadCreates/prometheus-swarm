import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

const variants = {
  default: 'bg-[var(--color-surface)] text-[var(--color-text-secondary)] border border-[var(--color-border)]',
  primary: 'bg-[var(--color-cyan)]/10 text-[var(--color-cyan)]',
  success: 'bg-[var(--color-cyan)]/10 text-[var(--color-cyan)]',
  warning: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)]',
  error: 'bg-[var(--color-alert)]/10 text-[var(--color-alert)]',
  info: 'bg-[var(--color-agent-scout)]/10 text-[var(--color-agent-scout)]',
  accent: 'bg-[var(--color-accent)]/10 text-[var(--color-accent)]',
};

const sizes = {
  sm: 'px-2 py-0.5 text-[var(--text-caption)]',
  md: 'px-2.5 py-1 text-[var(--text-label)]',
} as const;

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
}

export function Badge({ className, variant = 'default', size = 'sm', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[var(--radius-sm)] font-medium leading-none',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
