'use client';

interface OllamaDiagData {
  url?: string;
  model?: string;
  reachable?: boolean;
  response_time_ms?: number;
  models_available?: string[];
  model_found?: boolean;
  error?: string | null;
  suggestions?: string[];
}

interface OllamaDiagModalProps {
  diag: OllamaDiagData;
  onDismiss: () => void;
}

export default function OllamaDiagModal({ diag, onDismiss }: OllamaDiagModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        <h2 className="text-lg font-bold text-red-600 dark:text-red-400 mb-4">ollama not available</h2>

        <div className="space-y-3 text-sm">
          {/* Connection status */}
          <div className="flex items-center gap-2">
            <span
              data-testid="status-dot"
              className={`inline-block w-2.5 h-2.5 rounded-full ${diag.reachable ? 'bg-green-500' : 'bg-red-500'}`}
            />
            <span className="text-gray-700 dark:text-gray-300">
              {diag.reachable ? 'connected' : 'not reachable'}
            </span>
          </div>

          {/* URL & model */}
          <div className="text-gray-600 dark:text-gray-400">
            <p><span className="font-medium">url:</span> {diag.url}</p>
            <p><span className="font-medium">model:</span> {diag.model}</p>
            {diag.reachable && (
              <p><span className="font-medium">response:</span> {diag.response_time_ms}ms</p>
            )}
          </div>

          {/* Error */}
          {diag.error && (
            <p className="text-red-600 dark:text-red-400 font-medium">{diag.error}</p>
          )}

          {/* Available models */}
          {diag.reachable && diag.models_available && diag.models_available.length > 0 && (
            <div>
              <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">available models:</p>
              <div className="flex flex-wrap gap-1">
                {diag.models_available.map((m: string) => (
                  <span key={m} className="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs font-mono">{m}</span>
                ))}
              </div>
            </div>
          )}

          {/* Suggestions */}
          {diag.suggestions && diag.suggestions.length > 0 && (
            <div>
              <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">suggestions:</p>
              <ol className="list-decimal list-inside space-y-1 text-gray-600 dark:text-gray-400">
                {diag.suggestions.map((s: string, i: number) => (
                  <li key={i} className="font-mono text-xs">{s}</li>
                ))}
              </ol>
            </div>
          )}
        </div>

        <button
          onClick={onDismiss}
          className="mt-5 w-full py-2 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 rounded text-sm font-medium transition-colors"
        >
          dismiss
        </button>
      </div>
    </div>
  );
}
