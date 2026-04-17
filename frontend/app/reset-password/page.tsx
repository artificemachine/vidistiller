'use client';

import { useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get('token');

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  if (!token) {
    return (
      <div className="min-h-screen bg-bg-light dark:bg-bg-dark flex items-center justify-center px-4">
        <div className="bg-card-light dark:bg-card-dark rounded-16 shadow-lg dark:shadow-gray-900 p-10 w-full max-w-[420px] text-center">
          <h1 className="text-2xl font-bold text-text-dark dark:text-text-light mb-4">
            invalid reset link
          </h1>
          <p className="text-text-muted mb-6">
            this password reset link is invalid or has expired.
          </p>
          <Link
            href="/forgot-password"
            className="inline-block bg-primary hover:opacity-90 text-white font-bold py-2 px-6 rounded-lg transition"
          >
            request a new link
          </Link>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    if (!/[A-Z]/.test(newPassword)) {
      setError('Password must contain at least one uppercase letter.');
      return;
    }

    if (!/[a-z]/.test(newPassword)) {
      setError('Password must contain at least one lowercase letter.');
      return;
    }

    if (!/\d/.test(newPassword)) {
      setError('Password must contain at least one digit.');
      return;
    }

    setLoading(true);

    try {
      const res = await apiClient.post('/auth/reset-password', {
        token,
        new_password: newPassword,
      });
      setSuccess(res.data.message);
      setTimeout(() => router.push('/login'), 2000);
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      let msg = 'Failed to reset password. The link may have expired.';
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
            reset password
          </h1>
          <p className="text-sm text-text-muted">
            enter your new password below
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label htmlFor="new-password" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              new password
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                id="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full px-4 pr-10 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
                placeholder="min. 8 characters"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-text-muted hover:text-text-dark dark:hover:text-text-light"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074l-1.78-1.781zm4.261 4.26l1.514 1.515a2.003 2.003 0 012.45 2.45l1.514 1.514a4 4 0 00-5.478-5.478z" clipRule="evenodd" />
                    <path d="M12.454 16.697L9.75 13.992a4 4 0 01-3.742-3.741L2.335 6.578A9.98 9.98 0 00.458 10c1.274 4.057 5.065 7 9.542 7 .847 0 1.669-.105 2.454-.303z" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
                    <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div className="mb-6">
            <label htmlFor="confirm-password" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              confirm new password
            </label>
            <input
              type={showPassword ? 'text' : 'password'}
              id="confirm-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="confirm your password"
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
            {loading ? 'updating...' : 'update password'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm">
          <Link href="/login" className="text-accent-orange hover:underline">
            back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-bg-light dark:bg-bg-dark flex items-center justify-center">
        <div className="text-text-muted">loading...</div>
      </div>
    }>
      <ResetPasswordForm />
    </Suspense>
  );
}
