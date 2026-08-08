'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';
import type { LlmStatus } from '@/components/LlmStatusCard';

type FetchState = 'loading' | 'done' | 'failed';

/**
 * Compact model-connection status pill for the top navbar.
 *
 * Shows a colored dot + the active provider/model (from GET /diagnostics/llm):
 * green = reachable + model found, amber = reachable but model not available,
 * red = unreachable / api key rejected. Refreshes on click and every 60s.
 * Renders nothing when unauthenticated or the endpoint is unavailable.
 */
export default function LlmNavStatus() {
  const { isAuthenticated } = useAuthStore();
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [fetchState, setFetchState] = useState<FetchState>('loading');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    setFetchState('loading');
    try {
      const res = await apiClient.get('/diagnostics/llm');
      setStatus(res.data);
      setFetchState('done');
    } catch {
      setStatus(null);
      setFetchState('failed');
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    fetchStatus();
    timerRef.current = setInterval(fetchStatus, 60_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isAuthenticated, fetchStatus]);

  // Hide entirely when unauthenticated or the endpoint is unavailable.
  if (!isAuthenticated || fetchState === 'failed') return null;

  let dotClass = 'bg-gray-400';
  let title = 'checking llm status...';
  if (fetchState === 'done' && status) {
    if (status.auth_ok === false) {
      dotClass = 'bg-red-500';
      title = 'api key rejected';
    } else if (!status.reachable) {
      dotClass = 'bg-red-500';
      title = 'not reachable';
    } else if (!status.model_found) {
      dotClass = 'bg-amber-500';
      title = 'reachable, model not available';
    } else {
      dotClass = 'bg-green-500';
      title = 'ready';
    }
  }

  const detail = fetchState === 'done' && status
    ? `${title} · ${status.base_url || ''}${status.fleet_node ? ` · fleet: ${status.fleet_node}` : ''}${status.reachable ? ` · ${status.latency_ms}ms` : ''}`
    : title;

  return (
    <button
      type="button"
      onClick={fetchStatus}
      title={detail.trim()}
      aria-label={`llm status: ${title}`}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-bg-light dark:bg-input-bg text-text-muted hover:text-text-dark dark:hover:text-text-light text-xs font-mono transition-colors disabled:opacity-50"
      disabled={fetchState === 'loading'}
    >
      <span
        data-testid="llm-nav-dot"
        className={`inline-block w-2 h-2 rounded-full shrink-0 ${dotClass}`}
      />
      {fetchState === 'done' && status ? `${status.provider} · ${status.model || 'no model set'}` : 'checking...'}
    </button>
  );
}
