'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

interface RecentJob {
  job_id: string;
  status: string;
  youtube_url: string | null;
  video_title: string | null;
  created_at: string;
}

function getStatusColor(status: string) {
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
}

function timeAgo(dateString: string): string {
  const now = new Date();
  const date = new Date(dateString);
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [slideMode, setSlideMode] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [recentJobs, setRecentJobs] = useState<RecentJob[]>([]);
  const { isAuthenticated, isLoading: authLoading } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) return;
    apiClient.get('/jobs?limit=100')
      .then((res) => setRecentJobs(res.data))
      .catch(() => {});
  }, [isAuthenticated]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!isAuthenticated) {
      router.push('/login');
      return;
    }

    setLoading(true);

    try {
      const response = await apiClient.post(
        '/jobs',
        { youtube_url: url, output_format: 'markdown', extract_snapshots: true, is_slide_mode: slideMode }
      );
      router.push(`/jobs/${response.data.job_id}`);
    } catch (err: any) {
      setError(err.response?.data?.message || 'Failed to create job');
      setLoading(false);
    }
  };

  const handleImportJob = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!importFile) return;
    setImportError('');
    setImporting(true);

    try {
      const text = await importFile.text();
      const data = JSON.parse(text);
      const response = await apiClient.post('/jobs/import', data);
      router.push(`/jobs/${response.data.job_id}`);
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.response?.data?.message;
      setImportError(detail || 'Failed to import job. Check the file and try again.');
      setImporting(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-light dark:bg-bg-dark">
      <div className="max-w-4xl mx-auto px-4 py-12">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-semibold text-text-dark dark:text-text-light mb-4">
            video to doc (markdown)
          </h1>
          <p className="text-base text-text-muted text-center">
            convert into beautiful, searchable documents with snapshots and slides
          </p>
          <div className="flex flex-wrap justify-center gap-3 mt-4">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-card-light dark:bg-card-dark text-text-dark dark:text-text-light border border-border-light dark:border-border-dark">
              timestamped transcripts
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-card-light dark:bg-card-dark text-text-dark dark:text-text-light border border-border-light dark:border-border-dark">
              obsidian export
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium bg-card-light dark:bg-card-dark text-text-dark dark:text-text-light border border-border-light dark:border-border-dark">
              slide detection
            </span>
          </div>
        </div>

        <div className="flex flex-wrap justify-center gap-6 mt-6 mb-2 text-sm text-text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-green-500 inline-block" />
            500+ videos converted
          </span>
          <span>free · no api key required</span>
          <span>works with any youtube video</span>
        </div>

        <div className="bg-card-light dark:bg-surface rounded-16 shadow-lg dark:shadow-gray-900 p-6 mb-8 max-w-[600px] mx-auto">
          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <div>
              <label htmlFor="url" className="block text-[14px] font-semibold text-text-dark dark:text-text-light mb-2">
                youtube url
              </label>
              <input
                type="url"
                id="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                className="w-full px-4 h-12 rounded-lg bg-card-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:outline-none"
                required
              />
            </div>

            <div className="flex rounded-lg bg-card-light dark:bg-input-bg h-14 p-1">
              <button
                type="button"
                onClick={() => setSlideMode(true)}
                className={`flex-1 flex items-center justify-center rounded-md text-[13px] font-semibold transition-colors ${slideMode ? 'bg-primary text-bg-dark' : 'text-text-muted'}`}
              >
                presentation mode
              </button>
              <button
                type="button"
                onClick={() => setSlideMode(false)}
                className={`flex-1 flex items-center justify-center rounded-md text-[13px] font-semibold transition-colors ${!slideMode ? 'bg-primary text-bg-dark' : 'text-text-muted'}`}
              >
                transcript mode
              </button>
            </div>

            {error && (
              <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || authLoading}
              className="w-full bg-accent-submit hover:opacity-90 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-semibold h-12 px-4 rounded-lg transition"
            >
              {authLoading ? 'loading...' : loading ? 'loading job page...' : 'create document'}
            </button>
          </form>
        </div>

        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-text-muted hover:text-text-dark dark:hover:text-text-light transition-colors">
            have an exported .json? import it
          </summary>
          <div className="mt-3 bg-card-light dark:bg-card-dark rounded-lg shadow dark:shadow-gray-900 p-6">
            <form onSubmit={handleImportJob}>
              <div className="mb-4">
                <div
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full px-4 py-4 border-2 border-dashed border-border-light dark:border-border-dark rounded-lg bg-bg-light dark:bg-bg-dark text-center cursor-pointer hover:border-primary transition-colors"
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    id="importFile"
                    accept=".json"
                    className="hidden"
                    onChange={(e) => {
                      setImportFile(e.target.files?.[0] || null);
                      setImportError('');
                    }}
                  />
                  {importFile ? (
                    <div className="flex items-center justify-center gap-2">
                      <svg width="20" height="20" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" className="text-green-600 dark:text-green-400">
                        <path d="M11 13H3a1 1 0 01-1-1V2a1 1 0 011-1h6l3 3v8a1 1 0 01-1 1z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M9 1v3h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <span className="text-gray-900 dark:text-gray-50 font-medium text-sm">{importFile.name}</span>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setImportFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
                        className="text-gray-400 hover:text-red-500 ml-2"
                      >
                        &times;
                      </button>
                    </div>
                  ) : (
                    <p className="text-gray-500 dark:text-gray-400 text-sm">
                      click to select a <span className="font-mono">.json</span> export file
                    </p>
                  )}
                </div>
              </div>

              {importError && (
                <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400">
                  {importError}
                </div>
              )}

              <button
                type="submit"
                disabled={!importFile || importing}
                className="w-full bg-border-dark hover:opacity-80 disabled:bg-gray-400 dark:disabled:bg-gray-700 text-white font-semibold py-2 px-4 rounded-lg transition text-sm"
              >
                {importing ? 'importing...' : 'import job'}
              </button>
            </form>
          </div>
        </details>

        {recentJobs.length > 0 && (
          <div className="bg-card-light dark:bg-card-dark rounded-lg shadow-lg dark:shadow-gray-900 p-8 mt-8">
            <h2 className="text-lg font-semibold text-text-dark dark:text-text-light mb-4">
              recent conversions
            </h2>
            <div className="max-h-96 overflow-y-auto">
              <ul className="divide-y divide-border-light dark:divide-border-dark">
                {recentJobs.map((job) => (
                  <li key={job.job_id}>
                    <Link
                      href={`/jobs/${job.job_id}`}
                      className="flex items-center justify-between py-3 px-2 rounded hover:bg-bg-light dark:hover:bg-border-dark/30 transition-colors"
                    >
                      <div className="min-w-0 flex-1 mr-4">
                        <p className="text-sm font-medium text-text-dark dark:text-text-light truncate">
                          {job.video_title || (job.youtube_url ? job.youtube_url.slice(0, 60) : job.job_id)}
                        </p>
                        <p className="text-xs text-text-dark/50 dark:text-text-light/50 mt-0.5">
                          {timeAgo(job.created_at)}
                        </p>
                      </div>
                      <span className={`flex-shrink-0 px-2.5 py-0.5 rounded-full text-xs font-semibold ${getStatusColor(job.status)}`}>
                        {job.status}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
