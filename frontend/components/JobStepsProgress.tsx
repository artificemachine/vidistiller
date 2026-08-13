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

export default function JobStepsProgress({
  steps,
  onRetry,
}: {
  steps: JobStep[];
  onRetry?: (stepName: string) => void;
}) {
  if (!steps.length) return null;

  return (
    <section aria-label="Processing steps" className="space-y-2 rounded-lg border border-border-light p-3 dark:border-border-dark">
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
