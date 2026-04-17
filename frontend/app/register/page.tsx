'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { useAuthStore } from '@/lib/authStore';

export default function RegisterPage() {
  const router = useRouter();
  const setUser = useAuthStore((s) => s.setUser);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password.length < 8) {
      setError('password must be at least 8 characters');
      return;
    }

    if (!/[A-Z]/.test(password)) {
      setError('password must contain at least one uppercase letter');
      return;
    }

    if (password !== confirmPassword) {
      setError('passwords do not match');
      return;
    }

    setLoading(true);

    try {
      await apiClient.post('/auth/register', {
        username,
        email,
        password,
        ...(fullName ? { full_name: fullName } : {}),
      });

      // Auto-login after registration
      const loginRes = await apiClient.post('/auth/login', { username, password });
      const { access_token, refresh_token } = loginRes.data;
      localStorage.setItem('access_token', access_token);
      if (refresh_token) {
        localStorage.setItem('refresh_token', refresh_token);
      }
      document.cookie = `auth_token=${access_token}; path=/; max-age=${60 * 60 * 24 * 7}; SameSite=Lax`;

      const meRes = await apiClient.get('/auth/me');
      setUser(meRes.data);
      router.push('/');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      let msg = err.response?.data?.message || 'registration failed — please try again';
      if (Array.isArray(detail)) {
        msg = detail.map((d: any) => d.msg || String(d)).join('. ');
      } else if (typeof detail === 'string') {
        msg = detail;
      }
      setError(msg);
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-light dark:bg-bg-dark flex items-center justify-center px-4">
      <div className="bg-card-light dark:bg-card-dark rounded-16 shadow-lg dark:shadow-gray-900 p-10 w-full max-w-[420px]">
        <div className="text-center mb-6">
          <h2 className="text-3xl font-bold text-primary mb-4">vidistiller</h2>
          <h1 className="text-2xl font-semibold text-text-dark dark:text-text-light mb-2">
            create account
          </h1>
          <p className="text-sm text-text-muted">join and start converting tutorials</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label htmlFor="username" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              username
            </label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="choose a username"
              required
            />
          </div>

          <div className="mb-4">
            <label htmlFor="email" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              email
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

          <div className="mb-4">
            <label htmlFor="fullName" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              full name <span className="text-text-muted">(optional)</span>
            </label>
            <input
              type="text"
              id="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="John Doe"
            />
          </div>

          <div className="mb-4">
            <label htmlFor="password" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              password
            </label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="min. 8 characters"
              required
            />
          </div>

          <div className="mb-6">
            <label htmlFor="confirmPassword" className="block text-[13px] font-semibold text-text-dark dark:text-text-light mb-1">
              confirm password
            </label>
            <input
              type="password"
              id="confirmPassword"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-4 h-[44px] border border-border-light dark:border-transparent rounded-lg bg-bg-light dark:bg-input-bg text-text-dark dark:text-text-light placeholder-text-muted focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="confirm your password"
              required
            />
          </div>

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
            {loading ? 'creating account...' : 'create account'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-text-muted">
          already have an account?{' '}
          <Link href="/login" className="text-accent-orange font-semibold hover:underline">
            sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
