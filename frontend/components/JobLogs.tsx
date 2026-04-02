'use client';

import { useEffect, useRef } from 'react';

export interface LogEntry {
  id: number;
  job_id: number;
  level: 'info' | 'warning' | 'error';
  message: string;
  step: string | null;
  created_at: string;
}

interface JobLogsProps {
  logs: LogEntry[];
  isOpen: boolean;
  onToggle: () => void;
}

const levelColors: Record<string, string> = {
  info: 'text-green-400',
  warning: 'text-yellow-400',
  error: 'text-red-400',
};

const levelLabels: Record<string, string> = {
  info: 'INFO',
  warning: 'WARN',
  error: 'ERROR',
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export default function JobLogs({ logs, isOpen, onToggle }: JobLogsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasErrors = logs.some((l) => l.level === 'error');

  useEffect(() => {
    if (isOpen && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, isOpen]);

  return (
    <div className="border border-border-dark rounded-lg overflow-hidden">
      {/* Toggle header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 bg-card-dark hover:bg-border-dark text-text-light text-sm font-medium transition-colors"
      >
        <svg
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        <span>processing logs</span>
        {logs.length > 0 && (
          <span className="bg-border-dark text-text-light text-xs px-1.5 py-0.5 rounded-full">
            {logs.length}
          </span>
        )}
        {hasErrors && (
          <span className="w-2 h-2 bg-red-500 rounded-full ml-auto" />
        )}
      </button>

      {/* Log content */}
      {isOpen && (
        <div
          ref={scrollRef}
          className="bg-bg-dark max-h-60 overflow-y-auto p-3 font-mono text-xs leading-relaxed"
        >
          {logs.length === 0 ? (
            <p className="text-text-light/40">no logs yet...</p>
          ) : (
            logs.map((log) => (
              <div key={log.id} className="flex gap-2 py-0.5">
                <span className="text-text-light/50 whitespace-nowrap shrink-0">
                  {formatTime(log.created_at)}
                </span>
                <span className={`whitespace-nowrap shrink-0 ${levelColors[log.level]}`}>
                  [{levelLabels[log.level]}]
                </span>
                {log.step && (
                  <span className="text-text-light/50 whitespace-nowrap shrink-0">
                    {log.step}:
                  </span>
                )}
                <span className="text-text-light">{log.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
