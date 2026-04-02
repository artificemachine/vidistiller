'use client';

interface ProcessingStatusProps {
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress?: number;
  message?: string;
}

export default function ProcessingStatus({ status, progress = 0, message }: ProcessingStatusProps) {
  const statusConfig = {
    pending: { color: 'bg-warning/20 text-warning', label: 'pending' },
    processing: { color: 'bg-info/20 text-info', label: 'processing' },
    completed: { color: 'bg-success/20 text-success', label: 'completed' },
    failed: { color: 'bg-destructive/20 text-destructive', label: 'failed' },
  };

  const config = statusConfig[status];

  return (
    <div className="w-full max-w-md mx-auto p-6 bg-card-light dark:bg-card-dark rounded-lg shadow-lg dark:shadow-gray-900">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-text-dark dark:text-text-light">status</h3>
        <span className={`px-3 py-1 rounded-full text-sm font-bold ${config.color}`}>
          {config.label}
        </span>
      </div>

      {status === 'processing' && (
        <div className="mb-4">
          <div className="flex justify-between text-sm text-text-dark/70 dark:text-text-light/70 mb-2">
            <span>progress</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-border-light dark:bg-border-dark rounded-full h-2">
            <div
              className="bg-primary h-2 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>
      )}

      {message && (
        <p className="text-text-dark/70 dark:text-text-light/70 text-sm">{message}</p>
      )}
    </div>
  );
}
