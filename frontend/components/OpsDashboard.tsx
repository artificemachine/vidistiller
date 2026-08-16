'use client';

import useSWR from 'swr';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';
import QueueStatus from '@/components/QueueStatus';

export interface OpsJobRow {
  job_id: string;
  owner_id: number | null;
  owner_username: string | null;
  status: string;
  error_message: string | null;
  admission_state: string;
  queue_reason: string | null;
  queue_position: number | null;
  sidecar_id: string | null;
  model: string | null;
  elapsed_seconds: number | null;
  progress: number | null;
  processing_mode: string | null;
  created_at: string | null;
}

export interface SidecarStatusRow {
  registered_id: string;
  label: string;
  healthy: boolean;
  served_models: string[];
  declared_model: string | null;
  running_requests: number;
  waiting_requests: number;
  reserved_slots: number;
  total_slots: number;
  vram_used_mib: number | null;
  vram_total_mib: number | null;
  stale: boolean;
}

const REFRESH_INTERVAL_MS = 10_000;

const fetcher = (url: string) => apiClient.get(url).then((res) => res.data);

const statusColor: Record<string, string> = {
  pending: 'bg-warning/20 text-warning',
  processing: 'bg-info/20 text-info',
  completed: 'bg-success/20 text-success',
  failed: 'bg-destructive/20 text-destructive',
  cancelled: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};

function statusBadgeClass(status: string): string {
  return statusColor[status] ?? 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200';
}

function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null) return '—';
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function formatLocal(date: string | null | undefined): string {
  if (!date) return '—';
  return new Date(date).toLocaleString();
}

function accessDenied(status: number | undefined): boolean {
  return status === 401 || status === 403 || status === 404;
}

function ProgressBar({ progress }: { progress: number | null }) {
  const value = progress == null ? 0 : Math.max(0, Math.min(100, progress));
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 bg-border-light dark:bg-border-dark rounded-full h-2 shrink-0">
        <div
          className="bg-primary h-2 rounded-full transition-all duration-300"
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-xs text-text-dark/70 dark:text-text-light/70 tabular-nums">
        {progress == null ? '—' : `${value}%`}
      </span>
    </div>
  );
}

function SidecarStrip({ sidecars }: { sidecars: SidecarStatusRow[] }) {
  if (sidecars.length === 0) {
    return (
      <p className="text-sm text-text-muted">no sidecars registered.</p>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {sidecars.map((sidecar) => {
        const model = sidecar.served_models[0] ?? sidecar.declared_model;
        return (
          <div
            key={sidecar.registered_id}
            data-testid="sidecar-card"
            className="rounded-lg border border-border-light dark:border-border-dark bg-card-light dark:bg-card-dark p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-text-dark dark:text-text-light truncate">
                {sidecar.label}
              </span>
              <span
                data-testid="sidecar-health"
                className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${
                  sidecar.healthy && !sidecar.stale ? 'bg-success' : 'bg-destructive'
                }`}
              />
            </div>
            <p className="text-[11px] text-text-muted font-mono truncate">{sidecar.registered_id}</p>
            <p className="mt-1.5 text-xs text-text-dark/70 dark:text-text-light/70 truncate">
              model: {model || '—'}
            </p>
            <p className="text-xs text-text-dark/70 dark:text-text-light/70">
              slots: {sidecar.reserved_slots}/{sidecar.total_slots} reserved
              {sidecar.stale && <span className="text-warning"> · stale</span>}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Operator global view (WP4): sanitized job table + live sidecar strip.
 * Endpoints are operator-gated and fail closed with 404 — when the caller is
 * not an operator we show a login-gated notice instead of an error wall.
 */
export default function OpsDashboard() {
  const { isAuthenticated, isLoading: authLoading } = useAuthStore();

  const { data: jobs, error: jobsError } = useSWR<OpsJobRow[]>('/ops/jobs', fetcher, {
    refreshInterval: REFRESH_INTERVAL_MS,
  });
  const { data: sidecars, error: sidecarsError } = useSWR<SidecarStatusRow[]>(
    '/ops/sidecars',
    fetcher,
    { refreshInterval: REFRESH_INTERVAL_MS }
  );

  if (authLoading) {
    return <p className="text-sm text-text-muted">loading operations...</p>;
  }

  if (!isAuthenticated) {
    return (
      <div className="rounded-lg border border-border-light dark:border-border-dark bg-card-light dark:bg-card-dark p-6 text-center">
        <p className="text-sm text-text-dark dark:text-text-light">
          log in with an operator account to view global jobs.
        </p>
        <Link
          href="/login"
          className="mt-3 inline-block rounded bg-primary px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          log in
        </Link>
      </div>
    );
  }

  const denied =
    accessDenied(jobsError?.response?.status) || accessDenied(sidecarsError?.response?.status);

  if (denied) {
    return (
      <div
        data-testid="ops-access-denied"
        className="rounded-lg border border-border-light dark:border-border-dark bg-card-light dark:bg-card-dark p-6 text-center"
      >
        <p className="text-sm text-text-dark dark:text-text-light">
          operator access required — the global operations view is restricted.
        </p>
        <p className="mt-1 text-xs text-text-muted">
          ask an administrator to grant the operator role to your account.
        </p>
      </div>
    );
  }

  const jobsLoading = !jobs && !jobsError;
  const sidecarsLoading = !sidecars && !sidecarsError;

  return (
    <div className="space-y-8">
      <section aria-label="Sidecar status">
        <h2 className="mb-3 text-lg font-semibold text-text-dark dark:text-text-light">sidecars</h2>
        {sidecarsLoading ? (
          <p className="text-sm text-text-muted">loading sidecars...</p>
        ) : (
          <SidecarStrip sidecars={sidecars ?? []} />
        )}
      </section>

      <section aria-label="Global jobs">
        <h2 className="mb-3 text-lg font-semibold text-text-dark dark:text-text-light">jobs</h2>
        {jobsLoading ? (
          <p className="text-sm text-text-muted">loading jobs...</p>
        ) : jobs && jobs.length === 0 ? (
          <p className="text-sm text-text-muted">no jobs yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-light dark:border-border-dark bg-card-light dark:bg-card-dark">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="bg-bg-light dark:bg-border-dark/20">
                <tr>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">owner</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">status</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">admission</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">sidecar / model</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">elapsed</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">progress</th>
                  <th className="px-4 py-3 font-semibold text-text-dark dark:text-text-light">created (local)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light dark:divide-border-dark">
                {(jobs ?? []).map((job) => (
                  <tr key={job.job_id} className="hover:bg-bg-light dark:hover:bg-border-dark/20">
                    <td className="px-4 py-3">
                      <span className="font-medium text-text-dark dark:text-text-light">
                        {job.owner_username || '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${statusBadgeClass(job.status)}`}>
                        {job.status}
                      </span>
                      {job.error_message && (
                        <p className="mt-0.5 text-[11px] text-destructive">{job.error_message}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <QueueStatus
                        admissionState={job.admission_state}
                        queueReason={job.queue_reason}
                        queuePosition={job.queue_position}
                      />
                    </td>
                    <td className="px-4 py-3 text-text-dark/80 dark:text-text-light/80">
                      {job.sidecar_id ? (
                        <span className="font-mono text-xs">{job.sidecar_id}</span>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                      {job.model && (
                        <span className="ml-1 text-xs text-text-muted">({job.model})</span>
                      )}
                      {job.processing_mode && job.processing_mode !== 'standard' && (
                        <p className="text-[11px] text-text-muted">{job.processing_mode}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-text-dark/80 dark:text-text-light/80 tabular-nums">
                      {formatElapsed(job.elapsed_seconds)}
                    </td>
                    <td className="px-4 py-3">
                      <ProgressBar progress={job.progress} />
                    </td>
                    <td className="px-4 py-3 text-text-dark/70 dark:text-text-light/70">
                      {formatLocal(job.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
