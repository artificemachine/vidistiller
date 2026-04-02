import { useEffect, useState } from 'react';
import { ProcessingJob, ProcessingJobStatus } from '@/types';
import { apiClient } from '@/services';

export function useProcessingStatus(jobId: string) {
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchJob = async () => {
      try {
        setLoading(true);
        const data = await apiClient.get<ProcessingJob>(`/jobs/${jobId}`);
        setJob(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch job');
      } finally {
        setLoading(false);
      }
    };

    fetchJob();
    const interval = setInterval(fetchJob, 3000);
    return () => clearInterval(interval);
  }, [jobId]);

  return { job, loading, error };
}

export function useLocalStorage(key: string, initialValue: string) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    const stored = localStorage.getItem(key);
    if (stored) setValue(stored);
  }, [key]);

  const setStoredValue = (newValue: string) => {
    setValue(newValue);
    localStorage.setItem(key, newValue);
  };

  return [value, setStoredValue] as const;
}
