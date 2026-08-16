'use client';

export type JobStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';

export interface JobStep {
  name: string;
  status: JobStepStatus;
  attempt: number;
  percent: number;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  metrics?: Record<string, unknown>;
}

export interface JobEta {
  eta_low_seconds?: number | null;
  eta_high_seconds?: number | null;
  confidence?: number | null;
}

const STEP_ORDER = ['download', 'transcribe', 'snapshots', 'slides', 'summarize', 'export'];

const statusStyle: Record<JobStepStatus, string> = {
  pending: 'bg-warning/20 text-warning',
  running: 'bg-info/20 text-info',
  completed: 'bg-success/20 text-success',
  failed: 'bg-destructive/20 text-destructive',
  skipped: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
  cancelled: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
};

function orderedSteps(steps: JobStep[]): JobStep[] {
  return [...steps].sort((left, right) => {
    const leftOrder = STEP_ORDER.indexOf(left.name);
    const rightOrder = STEP_ORDER.indexOf(right.name);
    return (leftOrder < 0 ? STEP_ORDER.length : leftOrder) - (rightOrder < 0 ? STEP_ORDER.length : rightOrder);
  });
}

function formatEtaSeconds(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes > 0 ? `${hours}h ${remMinutes}m` : `${hours}h`;
}

function etaText(eta: JobEta): string | null {
  const low = eta.eta_low_seconds;
  const high = eta.eta_high_seconds;
  if (low != null && high != null) {
    const [from, to] = low <= high ? [low, high] : [high, low];
    return `eta ${formatEtaSeconds(from)}–${formatEtaSeconds(to)}`;
  }
  if (low != null) return `eta ~${formatEtaSeconds(low)}`;
  if (high != null) return `eta up to ${formatEtaSeconds(high)}`;
  return null;
}

function confidenceLabel(confidence: number): string {
  if (confidence >= 0.7) return 'high';
  if (confidence >= 0.4) return 'medium';
  return 'low';
}

export default function JobStepsProgress({
  steps,
  onRetry,
  overallProgress,
  eta,
}: {
  steps: JobStep[];
  onRetry?: (stepName: string) => void;
  overallProgress?: number | null;
  eta?: JobEta | null;
}) {
  if (!steps.length && overallProgress == null && !eta) return null;

  const progress = overallProgress == null ? null : Math.max(0, Math.min(100, overallProgress));
  const etaLine = eta ? etaText(eta) : null;

  return (
    <section aria-label="Processing steps" className="space-y-2 rounded-lg border border-border-light p-3 dark:border-border-dark">
      {progress != null && (
        <div className="rounded-md bg-card-light p-3 dark:bg-card-dark">
          <div className="flex items-center justify-between text-xs text-text-dark/70 dark:text-text-light/70">
            <span>overall progress</span>
            <span data-testid="overall-progress" className="tabular-nums">{progress}%</span>
          </div>
          <div className="mt-1.5 h-2 w-full rounded-full bg-border-light dark:bg-border-dark">
            <div
              className="h-2 rounded-full bg-primary transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {etaLine && (
            <p data-testid="eta-range" className="mt-1.5 text-xs text-text-dark/70 dark:text-text-light/70">
              {etaLine}
              {eta?.confidence != null && (
                <span> · {confidenceLabel(eta.confidence)} confidence</span>
              )}
            </p>
          )}
        </div>
      )}
      {orderedSteps(steps).map((step) => (
        <div key={step.name} className="rounded-md bg-card-light p-3 dark:bg-card-dark">
          <div className="flex items-center justify-between gap-3">
            <span data-testid="job-step-name" className="font-medium">{step.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle[step.status]}`}>
              {step.status}
            </span>
          </div>
          <p className="mt-1 text-xs text-text-dark/70 dark:text-text-light/70">
            attempt {step.attempt} · {step.percent}%
          </p>
          {step.started_at && <p className="text-xs text-text-dark/70 dark:text-text-light/70">started {step.started_at}</p>}
          {step.finished_at && <p className="text-xs text-text-dark/70 dark:text-text-light/70">finished {step.finished_at}</p>}
          {step.error_message && <p className="mt-1 text-xs text-destructive">{step.error_message}</p>}
          {step.status === 'failed' && onRetry && (
            <button
              type="button"
              className="mt-2 rounded bg-primary px-2 py-1 text-xs text-white"
              onClick={() => onRetry(step.name)}
              aria-label={`Retry ${step.name}`}
            >
              Retry
            </button>
          )}
        </div>
      ))}
    </section>
  );
}

export { STEP_ORDER };
