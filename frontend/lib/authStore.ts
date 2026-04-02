import { create } from 'zustand';
import axios from 'axios';
import apiClient, { setAccessToken, API_URL } from './api';

interface User {
  id: number;
  username: string;
  email: string;
  full_name?: string;
  is_active: boolean;
  llm_provider?: string;
  llm_model?: string;
  llm_ollama_url?: string;
  has_api_key?: boolean;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  logout: () => void;
  initialize: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  setUser: (user) => set({ user, isAuthenticated: !!user }),

  logout: () => {
    // Fire-and-forget: tell the backend to clear the HttpOnly auth_token cookie.
    // Must happen before setAccessToken(null) so the Authorization header is still valid.
    apiClient.post('/auth/logout').catch(() => {/* cookie TTL will expire naturally */});
    setAccessToken(null);
    localStorage.removeItem('refresh_token');
    set({ user: null, isAuthenticated: false });
  },

  initialize: async () => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      set({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }

    try {
      const res = await axios.post(`${API_URL}/auth/refresh`, {}, {
        withCredentials: true,
        headers: { Authorization: `Bearer ${refreshToken}` },
      });
      // Backend sets the HttpOnly auth_token cookie via Set-Cookie header automatically.
      const { access_token, refresh_token: newRefreshToken } = res.data;
      setAccessToken(access_token);
      if (newRefreshToken) {
        localStorage.setItem('refresh_token', newRefreshToken);
      }
    } catch {
      localStorage.removeItem('refresh_token');
      set({ user: null, isAuthenticated: false, isLoading: false });
      return;
    }

    try {
      const res = await apiClient.get('/auth/me');
      set({ user: res.data, isAuthenticated: true, isLoading: false });
    } catch {
      // Don't clear refresh token — the interceptor handles refresh failures.
      // Keep it so the next page load can retry.
      setAccessToken(null);
      document.cookie = 'auth_token=; path=/; max-age=0';
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
