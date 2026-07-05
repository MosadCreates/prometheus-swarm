import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

const variants = {
  default: 'bg-[var(--color-surface)] text-[var(--color-text-secondary)] border border-[var(--color-border)]',
  primary: 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
  success: 'bg-[var(--color-success)]/10 text-[var(--color-success)]',
  warning: 'bg-[var(--color-warning)]/10 text-[var(--color-warning)]',
  error: 'bg-[var(--color-error)]/10 text-[var(--color-error)]',
  info: 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]',
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
