'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import Link from 'next/link';
import { useAuthStore } from '@/lib/authStore';

interface Job {
  job_id: string;
  status: string;
  summarize_status?: string;
  video_title?: string;
  created_at: string;
  updated_at: string;
}

type SortBy = 'newest' | 'oldest' | 'status_asc' | 'status_desc';

const STATUS_ORDER: Record<string, number> = {
  pending: 0,
  processing: 1,
  completed: 2,
  failed: 3,
};

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sortBy, setSortBy] = useState<SortBy>('newest');
  const [filterMonth, setFilterMonth] = useState('all');
  const { isAuthenticated, isLoading: authLoading } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [authLoading, isAuthenticated, router]);

  const fetchJobs = useCallback(async () => {
    setError('');
    setLoading(true);
    try {
      const response = await apiClient.get('/jobs?limit=50');
      setJobs(response.data);
    } catch (err: any) {
      setError('Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) fetchJobs();
  }, [isAuthenticated, fetchJobs]);

  const handleCancel = useCallback(async (jobId: string) => {
    if (!confirm('Are you sure you want to stop this job?')) return;
    try {
      await apiClient.post(`/jobs/${jobId}/cancel`);
      setJobs((prev) =>
        prev.map((j) =>
          j.job_id === jobId ? { ...j, status: 'failed' } : j
        )
      );
    } catch (err: any) {
      const msg = err.response?.data?.message || 'Failed to cancel job';
      alert(msg);
    }
  }, []);

  const handleStopAll = useCallback(async () => {
    const active = jobs.filter(
      (j) => j.status === 'pending' || j.status === 'processing'
    );
    if (active.length === 0) {
      alert('No active jobs to stop.');
      return;
    }
    if (!confirm(`Stop ${active.length} active job${active.length > 1 ? 's' : ''}?`)) return;
    try {
      await Promise.all(
        active.map((j) => apiClient.post(`/jobs/${j.job_id}/cancel`))
      );
      setJobs((prev) =>
        prev.map((j) =>
          j.status === 'pending' || j.status === 'processing'
            ? { ...j, status: 'failed' }
            : j
        )
      );
    } catch {
      alert('Some jobs could not be stopped.');
    }
  }, [jobs]);

  const handleClearHistory = useCallback(async () => {
    const deletable = jobs.filter(
      (j) => j.status === 'completed' || j.status === 'failed'
    );
    if (deletable.length === 0) {
      alert('No completed or failed jobs to clear.');
      return;
    }
    if (!confirm(`Delete ${deletable.length} completed/failed job${deletable.length > 1 ? 's' : ''}?`)) return;
    try {
      await Promise.all(
        deletable.map((j) => apiClient.delete(`/jobs/${j.job_id}`))
      );
      setJobs((prev) =>
        prev.filter((j) => j.status !== 'completed' && j.status !== 'failed')
      );
    } catch {
      alert('Some jobs could not be deleted.');
    }
  }, [jobs]);

  const availableMonths = useMemo(() => {
    const months = new Set<string>();
    jobs.forEach((j) => {
      const d = new Date(j.created_at);
      months.add(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    });
    return Array.from(months).sort().reverse();
  }, [jobs]);

  const formatMonthLabel = (ym: string) => {
    const [year, month] = ym.split('-');
    const d = new Date(Number(year), Number(month) - 1);
    return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  };

  const filteredJobs = useMemo(() => {
    let result = jobs;

    if (filterMonth !== 'all') {
      result = result.filter((j) => {
        const d = new Date(j.created_at);
        const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        return ym === filterMonth;
      });
    }

    result = [...result].sort((a, b) => {
      switch (sortBy) {
        case 'newest':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'oldest':
          return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        case 'status_asc':
          return (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
        case 'status_desc':
          return (STATUS_ORDER[b.status] ?? 99) - (STATUS_ORDER[a.status] ?? 99);
      }
    });

    return result;
  }, [jobs, filterMonth, sortBy]);

  const handleColumnSort = (column: 'status' | 'created') => {
    if (column === 'status') {
      setSortBy((prev) => (prev === 'status_asc' ? 'status_desc' : 'status_asc'));
    } else {
      setSortBy((prev) => (prev === 'newest' ? 'oldest' : 'newest'));
    }
  };

  const sortArrow = (column: 'status' | 'created') => {
    if (column === 'status') {
      if (sortBy === 'status_asc') return ' \u2191';
      if (sortBy === 'status_desc') return ' \u2193';
    }
    if (column === 'created') {
      if (sortBy === 'newest') return ' \u2193';
      if (sortBy === 'oldest') return ' \u2191';
    }
    return '';
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-success/20 text-success';
      case 'processing':
        return 'bg-info/20 text-info';
      case 'failed':
        return 'bg-destructive/20 text-destructive';
      default:
        return 'bg-warning/20 text-warning';
    }
  };

  if (authLoading || loading) {
    return <div className="text-center py-12 text-text-dark dark:text-text-light">loading jobs...</div>;
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto py-8 px-4">
        <h1 className="text-3xl font-bold text-text-dark dark:text-text-light mb-8">jobs dashboard</h1>
        <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={fetchJobs}
            className="ml-4 px-4 py-1.5 text-sm font-semibold bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 rounded hover:bg-red-200 dark:hover:bg-red-900/60 transition-colors"
          >
            retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto py-8 px-4">
      <h1 className="text-3xl font-bold text-text-dark dark:text-text-light mb-8">jobs dashboard</h1>

      {jobs.length > 0 && (
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <select
            value={filterMonth}
            onChange={(e) => setFilterMonth(e.target.value)}
            className="px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-bg-light dark:bg-bg-dark text-text-dark dark:text-text-light text-sm"
          >
            <option value="all">all months</option>
            {availableMonths.map((ym) => (
              <option key={ym} value={ym}>{formatMonthLabel(ym)}</option>
            ))}
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            className="px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-bg-light dark:bg-bg-dark text-text-dark dark:text-text-light text-sm"
          >
            <option value="newest">newest first</option>
            <option value="oldest">oldest first</option>
            <option value="status_asc">status (a-z)</option>
            <option value="status_desc">status (z-a)</option>
          </select>

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleStopAll}
              className="px-4 py-2 rounded-lg border border-orange-400 dark:border-orange-600 text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/20 text-sm font-semibold"
            >
              stop all
            </button>
            <button
              onClick={handleClearHistory}
              className="px-4 py-2 rounded-lg border border-red-400 dark:border-red-600 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 text-sm font-semibold"
            >
              clear history
            </button>
          </div>
        </div>
      )}

      <div className="bg-card-light dark:bg-card-dark rounded-lg shadow dark:shadow-gray-900 overflow-hidden">
        {jobs.length === 0 ? (
          <div className="p-8">
            <h2 className="text-lg font-semibold text-text-dark dark:text-text-light mb-1">
              get started with youtube-model-feeder
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              follow these steps to get the most out of the app
            </p>
            <div className="space-y-3">
              {[
                { label: 'convert your first video', href: '/' },
                { label: 'capture snapshots while watching', href: null },
                { label: 'generate an ai summary', href: null },
                { label: 'export your documentation to obsidian', href: null },
                { label: 'import a saved job', href: null },
              ].map((step, i) => (
                <div key={i} className="flex items-center gap-3 text-sm text-gray-600 dark:text-gray-400">
                  <div className="h-5 w-5 rounded-full border-2 border-border-light dark:border-border-dark shrink-0" />
                  {step.href ? (
                    <Link href={step.href} className="hover:text-primary hover:underline">
                      {step.label}
                    </Link>
                  ) : (
                    <span>{step.label}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-bg-light dark:bg-border-dark/20">
              <tr>
                <th className="px-6 py-3 text-left text-sm font-semibold text-text-dark dark:text-text-light">job id</th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-text-dark dark:text-text-light">title</th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-text-dark dark:text-text-light">
                  <button
                    onClick={() => handleColumnSort('status')}
                    className="hover:text-primary"
                  >
                    status{sortArrow('status')}
                  </button>
                </th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-text-dark dark:text-text-light">
                  <button
                    onClick={() => handleColumnSort('created')}
                    className="hover:text-primary"
                  >
                    created{sortArrow('created')}
                  </button>
                </th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-text-dark dark:text-text-light">action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light dark:divide-border-dark">
              {filteredJobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-bg-light dark:hover:bg-border-dark/20">
                  <td className="px-6 py-4 text-sm text-text-dark dark:text-text-light font-mono">
                    {job.job_id.slice(0, 8)}...
                  </td>
                  <td className="px-6 py-4 text-sm text-text-dark dark:text-text-light max-w-xs truncate" title={job.video_title || ''}>
                    {job.video_title || <span className="text-text-dark/30 dark:text-text-light/30 italic">—</span>}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`px-3 py-1 rounded-full text-sm font-semibold ${getStatusColor(job.status)}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-text-dark/60 dark:text-text-light/60">
                    {new Date(job.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-sm flex items-center gap-3">
                    <Link
                      href={`/jobs/${job.job_id}`}
                      className="text-primary hover:opacity-80 font-semibold"
                    >
                      view
                    </Link>
                    <button
                      onClick={() => handleCancel(job.job_id)}
                      disabled={job.status === 'completed' || job.status === 'failed'}
                      className={
                        job.status === 'completed' || job.status === 'failed'
                          ? 'text-gray-400 dark:text-gray-600 cursor-not-allowed font-semibold'
                          : 'text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 font-semibold'
                      }
                    >
                      stop
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('Delete this job?')) return;
                        try {
                          await apiClient.delete(`/jobs/${job.job_id}`);
                          setJobs((prev) => prev.filter((j) => j.job_id !== job.job_id));
                        } catch {
                          alert('Failed to delete job.');
                        }
                      }}
                      className="text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 font-semibold"
                    >
                      clear
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
