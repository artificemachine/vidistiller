'use client';

import { useCallback, useEffect, useState } from 'react';
import apiClient from '@/lib/api';

export interface LlmStatus {
  provider: string;
  model: string | null;
  base_url: string | null;
  reachable: boolean;
  auth_ok: boolean | null;
  model_found: boolean;
  models_available: string[];
  latency_ms: number;
  error: string | null;
  fleet_node: string | null;
}

type FetchState = 'loading' | 'done' | 'failed';

interface LlmStatusCardProps {
  /** Change this value to force a re-check (e.g. after saving settings). */
  refreshToken?: number;
}

/**
 * Shows which LLM provider/model the account is configured for and whether
 * that endpoint is currently reachable (GET /diagnostics/llm).
 */
export default function LlmStatusCard({ refreshToken = 0 }: LlmStatusCardProps) {
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [fetchState, setFetchState] = useState<FetchState>('loading');

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
    fetchStatus();
  }, [fetchStatus, refreshToken]);

  // Derive the overall state for display.
  let dotClass = 'bg-gray-400';
  let headline = 'checking...';
  if (fetchState === 'failed') {
    dotClass = 'bg-gray-400';
    headline = 'status unavailable';
  } else if (fetchState === 'done' && status) {
    if (status.auth_ok === false) {
      dotClass = 'bg-red-500';
      headline = 'api key rejected';
    } else if (!status.reachable) {
      dotClass = 'bg-red-500';
      headline = 'not reachable';
    } else if (!status.model_found) {
      dotClass = 'bg-amber-500';
      headline = 'reachable, model not available';
    } else {
      dotClass = 'bg-green-500';
      headline = 'ready';
    }
  }

  return (
    <div className="rounded-xl p-5 bg-card-light dark:bg-card-dark flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-semibold text-text-dark dark:text-text-light">llm status</p>
        <button
          type="button"
          onClick={fetchStatus}
          disabled={fetchState === 'loading'}
          className="text-xs text-text-muted hover:text-text-dark dark:hover:text-text-light disabled:opacity-50 transition-colors"
        >
          refresh
        </button>
      </div>

      <div className="flex items-center gap-2">
        <span
          data-testid="llm-status-dot"
          className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${dotClass}`}
        />
        <span className="text-[13px] font-medium text-text-dark dark:text-text-light">
          {fetchState === 'done' && status ? `${status.provider} · ${status.model || 'no model set'}` : headline}
        </span>
        {fetchState === 'done' && status && (
          <span className="text-xs text-text-muted">— {headline}</span>
        )}
      </div>

      {fetchState === 'done' && status && (
        <div className="text-xs text-text-muted flex flex-col gap-1">
          {status.base_url && <p data-testid="llm-status-url">{status.base_url}</p>}
          {status.reachable && <p>{status.latency_ms}ms</p>}
          {status.fleet_node && <p>fleet node: {status.fleet_node}</p>}
          {status.error && <p className="text-red-600 dark:text-red-400">{status.error}</p>}
          {status.reachable && !status.model_found && status.models_available.length > 0 && (
            <p data-testid="llm-status-available">
              available: {status.models_available.slice(0, 5).join(', ')}
            </p>
          )}
        </div>
      )}

      {fetchState === 'failed' && (
        <p className="text-xs text-text-muted">could not fetch llm status from the server.</p>
      )}
    </div>
  );
}
