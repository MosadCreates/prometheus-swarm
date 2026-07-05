'use client';

import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  description?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, description, error, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-[var(--text-label)] font-medium text-[var(--color-text-primary)]">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'h-10 w-full rounded-[var(--radius-md)] border bg-[var(--color-bg)] px-3 text-sm text-[var(--color-text-primary)]',
            'placeholder:text-[var(--color-text-muted)]',
            'border-[var(--color-border)] focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20',
            'transition-all duration-[var(--duration-normal)]',
            'disabled:pointer-events-none disabled:opacity-50',
            error && 'border-[var(--color-error)] focus:border-[var(--color-error)] focus:ring-[var(--color-error)]/20',
            className,
          )}
          {...props}
        />
        {description && !error && (
          <p className="text-[var(--text-caption)] text-[var(--color-text-muted)]">{description}</p>
        )}
        {error && (
          <p className="text-[var(--text-caption)] text-[var(--color-error)]">{error}</p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
