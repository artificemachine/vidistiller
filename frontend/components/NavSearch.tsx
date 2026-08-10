'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

interface JobSearchResult {
  job_id: string;
  status: string;
  video_title: string | null;
  video_url: string | null;
  created_at: string;
}

const DEBOUNCE_MS = 300;

/**
 * Navbar search: finds jobs by video title, URL, or transcript keyword.
 * Debounced query against GET /jobs?q=... — click a result to open the job.
 */
export default function NavSearch() {
  const { isAuthenticated } = useAuthStore();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<JobSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await apiClient.get('/jobs', { params: { q, limit: 20 } });
      setResults(res.data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(query), DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, runSearch]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  if (!isAuthenticated) return null;

  const goToJob = (jobId: string) => {
    setOpen(false);
    setQuery('');
    setResults([]);
    router.push(`/jobs/${jobId}`);
  };

  return (
    <div ref={containerRef} className="relative">
      <input
        type="search"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="search conversions..."
        aria-label="search conversions"
        className="w-40 sm:w-56 px-3 py-1.5 rounded-full bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light text-sm placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-blue-500"
      />

      {open && query.trim() && (
        <div
          data-testid="nav-search-dropdown"
          className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto rounded-lg shadow-lg bg-card-light dark:bg-card-dark border border-gray-200 dark:border-gray-700 z-50"
        >
          {loading && (
            <div className="px-4 py-3 text-sm text-text-muted">searching...</div>
          )}
          {!loading && results.length === 0 && (
            <div className="px-4 py-3 text-sm text-text-muted">no matches</div>
          )}
          {!loading &&
            results.map((job) => (
              <button
                key={job.job_id}
                type="button"
                onClick={() => goToJob(job.job_id)}
                className="w-full text-left px-4 py-2 hover:bg-bg-light dark:hover:bg-input-bg transition-colors border-b border-gray-100 dark:border-gray-800 last:border-0"
              >
                <div className="text-sm font-medium text-text-dark dark:text-text-light truncate">
                  {job.video_title || job.video_url || job.job_id}
                </div>
                <div className="text-xs text-text-muted flex items-center gap-2">
                  <span>{job.status}</span>
                  <span>·</span>
                  <span>{new Date(job.created_at).toLocaleDateString()}</span>
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
