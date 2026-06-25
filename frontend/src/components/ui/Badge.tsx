import { Loader2 } from 'lucide-react';
import type { JobStatus } from '../../types';

interface StatusBadgeProps {
  status: JobStatus;
  size?: 'sm' | 'md';
}

export function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const statusConfig: Record<JobStatus, { label: string; class: string; icon?: React.ReactNode }> = {
    PENDING: {
      label: 'Queued',
      class: 'bg-surface-100 text-surface-600 border-surface-200',
    },
    RUNNING: {
      label: 'Processing',
      class: 'bg-primary-50 text-primary-600 border-primary-200',
      icon: <Loader2 className="w-3 h-3 animate-spin" />,
    },
    STORY_PROPOSED: {
      label: 'Review Story',
      class: 'bg-warning-500/10 text-warning-600 border-warning-500/20',
    },
    COMPLETED: {
      label: 'Completed',
      class: 'bg-success-500/10 text-success-600 border-success-500/20',
    },
    FAILED: {
      label: 'Failed',
      class: 'bg-error-500/10 text-error-600 border-error-500/20',
    },
  };

  const config = statusConfig[status];
  const sizeClass = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1';

  return (
    <span
      className={`
        inline-flex items-center gap-1.5 font-medium rounded-full border
        ${config.class}
        ${sizeClass}
      `}
    >
      {config.icon}
      {config.label}
    </span>
  );
}
