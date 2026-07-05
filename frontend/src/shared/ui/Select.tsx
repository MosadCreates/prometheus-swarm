'use client';

import { forwardRef, type SelectHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';
import { ChevronDown } from 'lucide-react';

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, id, children, ...props }, ref) => {
    const selectId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={selectId} className="text-[var(--text-label)] font-medium text-[var(--color-text-primary)]">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={cn(
              'h-10 w-full appearance-none rounded-[var(--radius-md)] border bg-[var(--color-bg)] px-3 pr-10 text-sm text-[var(--color-text-primary)]',
              'border-[var(--color-border)] focus:border-[var(--color-cyan)] focus:ring-2 focus:ring-[var(--color-cyan)]/20',
              'transition-all duration-[var(--duration-normal)]',
              'disabled:pointer-events-none disabled:opacity-50',
              error && 'border-[var(--color-alert)]',
              className,
            )}
            {...props}
          >
            {children}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-muted)] pointer-events-none" />
        </div>
        {error && <p className="text-[var(--text-caption)] text-[var(--color-alert)]">{error}</p>}
      </div>
    );
  },
);

Select.displayName = 'Select';
