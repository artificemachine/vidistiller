'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import SidecarSelector from '@/components/SidecarSelector';

interface VideoSubmissionProps {
  onSuccess?: (jobId: string) => void;
}

interface ExistingJob {
  job_id: string;
  status: string;
  created_at: string;
  video_title: string | null;
}

type SubmissionMode = 'url' | 'upload';

export default function VideoSubmission({ onSuccess }: VideoSubmissionProps) {
  const [mode, setMode] = useState<SubmissionMode>('url');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [duplicate, setDuplicate] = useState<ExistingJob | null>(null);
  const [sidecarPreference, setSidecarPreference] = useState('auto');
  const router = useRouter();

  const goToJob = (jobId: string) => {
    if (onSuccess) {
      onSuccess(jobId);
    } else {
      router.push(`/jobs/${jobId}`);
    }
  };

  const submitJob = async (force: boolean) => {
    setError('');
    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
      const response = await fetch(`${apiUrl}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_url: url,
          force,
          ...(sidecarPreference && sidecarPreference !== 'auto'
            ? { sidecar_preference: sidecarPreference }
            : {}),
        }),
      });

      if (response.status === 409) {
        const errorData = await response.json().catch(() => ({}));
        setDuplicate(errorData.existing_job || null);
        return;
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'failed to create job');
      }

      const data = await response.json();
      setDuplicate(null);
      goToJob(data.job_id); // Use job_id (UUID) instead of id
    } catch (err) {
      setError(err instanceof Error ? err.message : 'an error occurred');
    } finally {
      setLoading(false);
    }
  };

  const submitUpload = async () => {
    if (!file) return;
    setError('');
    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
      const formData = new FormData();
      formData.append('file', file);
      if (sidecarPreference && sidecarPreference !== 'auto') {
        formData.append('sidecar_preference', sidecarPreference);
      }

      const response = await fetch(`${apiUrl}/jobs/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'failed to upload file');
      }

      const data = await response.json();
      goToJob(data.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'an error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setDuplicate(null);
    if (mode === 'upload') {
      await submitUpload();
    } else {
      await submitJob(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-md mx-auto p-6">
      <div className="flex mb-4 border rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setMode('url')}
          aria-pressed={mode === 'url'}
          className={`flex-1 py-2 text-sm ${mode === 'url' ? 'bg-blue-500 text-white' : 'bg-white text-gray-700'}`}
        >
          video url
        </button>
        <button
          type="button"
          onClick={() => setMode('upload')}
          aria-pressed={mode === 'upload'}
          className={`flex-1 py-2 text-sm ${mode === 'upload' ? 'bg-blue-500 text-white' : 'bg-white text-gray-700'}`}
        >
          upload file
        </button>
      </div>

      {mode === 'url' ? (
        <div key="url-field" className="mb-4">
          <label className="block text-gray-700 mb-2">video url</label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="YouTube, Vimeo, Twitch, X.com, TikTok, Reddit, Rumble or direct .mp4..."
            className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            required
          />
        </div>
      ) : (
        <div key="file-field" className="mb-4">
          <label htmlFor="video-file-input" className="block text-gray-700 mb-2">
            video or audio file
          </label>
          <input
            id="video-file-input"
            type="file"
            accept=".mp4,.webm,.mov,.mkv,.avi,.m4v,.ogv,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      )}

      {error && <div className="text-red-500 mb-4">{error}</div>}

      <div className="mb-4">
        <SidecarSelector value={sidecarPreference} onChange={setSidecarPreference} disabled={loading} />
      </div>

      {duplicate && (
        <div
          data-testid="duplicate-warning"
          className="mb-4 p-3 rounded-lg border border-yellow-400 bg-yellow-50 text-sm text-yellow-800"
        >
          <p className="mb-2">
            already converted{duplicate.video_title ? `: ${duplicate.video_title}` : ''} (
            {new Date(duplicate.created_at).toLocaleDateString()}, {duplicate.status})
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => router.push(`/jobs/${duplicate.job_id}`)}
              className="px-3 py-1 rounded border border-yellow-600 hover:bg-yellow-100"
            >
              view existing
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => submitJob(true)}
              className="px-3 py-1 rounded border border-yellow-600 hover:bg-yellow-100 disabled:opacity-50"
            >
              convert anyway
            </button>
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={loading || (mode === 'upload' && !file)}
        className="w-full bg-blue-500 text-white py-2 rounded-lg hover:bg-blue-600 disabled:opacity-50"
      >
        {loading ? 'processing...' : 'convert to documentation'}
      </button>
    </form>
  );
}
