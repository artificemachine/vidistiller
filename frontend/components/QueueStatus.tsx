'use client';

interface QueueStatusProps {
  admissionState?: string | null;
  queueReason?: string | null;
  queuePosition?: number | null;
}

const admissionStyle: Record<string, string> = {
  queued: 'bg-warning/20 text-warning',
  admitted: 'bg-info/20 text-info',
  finished: 'bg-success/20 text-success',
  failed: 'bg-destructive/20 text-destructive',
};

/**
 * Admission state badge for a job row. Renders nothing when the backend has
 * not emitted admission fields yet (graceful degradation — admission state
 * is not part of JobResponse today).
 */
export default function QueueStatus({
  admissionState,
  queueReason,
  queuePosition,
}: QueueStatusProps) {
  if (!admissionState) return null;

  const style =
    admissionStyle[admissionState] ??
    'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200';

  return (
    <div className="flex flex-col items-start gap-0.5">
      <span
        data-testid="admission-state"
        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${style}`}
      >
        {admissionState}
      </span>
      {admissionState === 'queued' && (queueReason || queuePosition != null) && (
        <span className="text-[11px] text-text-dark/60 dark:text-text-light/60">
          {queueReason && <span>{queueReason}</span>}
          {queueReason && queuePosition != null && <span> · </span>}
          {queuePosition != null && (
            <span data-testid="queue-position">position #{queuePosition}</span>
          )}
        </span>
      )}
    </div>
  );
}
