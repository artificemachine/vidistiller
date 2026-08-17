'use client';

import { useEffect } from 'react';
import useSWR from 'swr';
import apiClient from '@/lib/api';

export interface AvailableSidecar {
  registered_id: string;
  label: string;
  capabilities: string[];
  healthy: boolean;
  available_slots: number;
}

const fetcher = (url: string) => apiClient.get(url).then((res) => res.data);

interface SidecarSelectorProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * Dropdown for the optional sidecar_preference on new jobs: "auto" plus the
 * registered sidecars from GET /api/sidecars/available. Falls back to
 * auto-only and disables the control when the endpoint is unavailable.
 */
export default function SidecarSelector({ value, onChange, disabled }: SidecarSelectorProps) {
  const { data, error } = useSWR<AvailableSidecar[]>('/sidecars/available', fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
  });

  const unavailable = Boolean(error) || (data != null && !Array.isArray(data));
  const sidecars = Array.isArray(data) ? data : [];

  // Never leave a stale sidecar id selected when the endpoint goes away.
  useEffect(() => {
    if (unavailable && value !== 'auto') onChange('auto');
  }, [unavailable, value, onChange]);

  return (
    <div>
      <label htmlFor="sidecarPreference" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1.5">
        sidecar preference
      </label>
      <select
        id="sidecarPreference"
        aria-label="sidecar preference"
        value={unavailable ? 'auto' : value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || unavailable}
        className="w-full px-3 h-10 border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light text-[13px] focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
      >
        <option value="auto">auto (default)</option>
        {sidecars.map((sidecar) => (
          <option key={sidecar.registered_id} value={sidecar.registered_id} disabled={!sidecar.healthy}>
            {sidecar.label} ({sidecar.registered_id})
            {sidecar.healthy ? ` — ${sidecar.available_slots} free` : ' — offline'}
          </option>
        ))}
      </select>
      {unavailable && (
        <p className="mt-1 text-xs text-text-muted">sidecar selection unavailable — using auto</p>
      )}
    </div>
  );
}
