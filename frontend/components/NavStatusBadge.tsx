'use client';

import { useJobStatus } from './JobStatusProvider';

const badgeConfig: Record<string, { label: string; className: string }> = {
  completed: { label: 'complete', className: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' },
  processing: { label: 'processing', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400' },
  failed: { label: 'failed', className: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400' },
  pending: { label: 'pending', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' },
};

export default function NavStatusBadge() {
  const { jobStatus } = useJobStatus();
  if (!jobStatus) return null;

  const config = badgeConfig[jobStatus];
  if (!config) return null;

  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${config.className}`}>
      {config.label}
    </span>
  );
}
