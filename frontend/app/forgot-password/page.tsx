'use client';

import { useState } from 'react';
import Link from 'next/link';
import apiClient from '@/lib/api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      const res = await apiClient.post('/auth/forgot-password', { email });
      setSuccess(res.data.message);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      let msg = 'Something went wrong. Please try again.';
      if (Array.isArray(detail)) {
        msg = detail.map((d: any) => d.msg || String(d)).join('. ');
      } else if (typeof detail === 'string') {
        msg = detail;
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-light dark:bg-bg-dark flex items-center justify-center px-4">
      <div className="bg-card-light dark:bg-card-dark rounded-16 shadow-lg dark:shadow-gray-900 p-10 w-full max-w-[420px]">
        <div className="text-center mb-6">
          <h2 className="text-3xl font-bold text-primary mb-4">vidistiller</h2>
          <h1 className="text-2xl font-semibold text-text-dark dark:text-text-light mb-2">
            forgot password
          </h1>
          <p className="text-sm text-text-muted">
            enter your email to reset your password
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label htmlFor="email" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              email address
            </label>
            <input
              type="email"
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="your@email.com"
              required
            />
          </div>

          {success && (
            <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-green-700 dark:text-green-400 text-sm">
              {success}
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-400 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-accent-orange hover:opacity-90 disabled:bg-gray-400 dark:disabled:bg-gray-600 text-white font-semibold h-12 px-4 rounded-lg transition"
          >
            {loading ? 'sending...' : 'send reset link'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm">
          <Link href="/login" className="text-accent-orange hover:underline inline-flex items-center gap-1">
            back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
