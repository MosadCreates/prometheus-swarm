'use client';

import { motion } from 'framer-motion';
import { cn } from '@/shared/utils/cn';

interface MetricCardProps {
  label: string;
  value: number | string;
  change?: string;
  index?: number;
}

export function MetricCard({ label, value, change, index = 0 }: MetricCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.3 }}
      className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] p-5"
    >
      <p className="text-xs text-[var(--color-text-muted)] mb-1">{label}</p>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-[var(--color-text-primary)]">{value}</span>
        {change && (
          <span className={cn('text-xs font-medium', change.startsWith('+') ? 'text-[var(--color-success)]' : 'text-[var(--color-error)]')}>
            {change}
          </span>
        )}
      </div>
    </motion.div>
  );
}
