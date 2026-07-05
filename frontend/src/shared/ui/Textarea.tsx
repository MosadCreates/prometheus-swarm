'use client';

import { forwardRef, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, id, ...props }, ref) => {
    const textareaId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={textareaId} className="text-[var(--text-label)] font-medium text-[var(--color-text-primary)]">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={textareaId}
          className={cn(
            'w-full rounded-[var(--radius-md)] border bg-[var(--color-bg)] px-3 py-2.5 text-sm text-[var(--color-text-primary)]',
            'placeholder:text-[var(--color-text-muted)]',
            'border-[var(--color-border)] focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/20',
            'transition-all duration-[var(--duration-normal)] resize-y min-h-[80px]',
            'disabled:pointer-events-none disabled:opacity-50',
            error && 'border-[var(--color-error)]',
            className,
          )}
          {...props}
        />
        {error && <p className="text-[var(--text-caption)] text-[var(--color-error)]">{error}</p>}
      </div>
    );
  },
);

Textarea.displayName = 'Textarea';
