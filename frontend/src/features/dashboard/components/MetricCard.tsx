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
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.2 }}
      className="bg-[var(--color-bg)] p-4"
    >
      <p className="text-[10px] font-mono text-[var(--color-text-muted)] mb-1">{label}</p>
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-mono font-semibold text-[var(--color-text-primary)]">{value}</span>
        {change && (
          <span className={cn('text-[10px] font-mono font-medium', change.startsWith('+') ? 'text-[var(--color-cyan)]' : 'text-[var(--color-alert)]')}>
            {change}
          </span>
        )}
      </div>
    </motion.div>
  );
}
