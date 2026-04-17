'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

interface VideoSubmissionProps {
  onSuccess?: (jobId: string) => void;
}

export default function VideoSubmission({ onSuccess }: VideoSubmissionProps) {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
      const response = await fetch(`${apiUrl}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_url: url }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'failed to create job');
      }

      const data = await response.json();
      const jobId = data.job_id; // Use job_id (UUID) instead of id

      if (onSuccess) {
        onSuccess(jobId);
      } else {
        router.push(`/jobs/${jobId}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'an error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-md mx-auto p-6">
      <div className="mb-4">
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

      {error && <div className="text-red-500 mb-4">{error}</div>}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-500 text-white py-2 rounded-lg hover:bg-blue-600 disabled:opacity-50"
      >
        {loading ? 'processing...' : 'convert to documentation'}
      </button>
    </form>
  );
}
