import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'text' | 'circular' | 'rectangular';
}

export function Skeleton({ className, variant = 'text', ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        'animate-pulse bg-[var(--color-border-light)]',
        variant === 'circular' && 'rounded-full',
        variant === 'rectangular' && 'rounded-[var(--radius-md)]',
        variant === 'text' && 'rounded-[var(--radius-sm)] h-4',
        className,
      )}
      {...props}
    />
  );
}
