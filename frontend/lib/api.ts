import axios, { AxiosInstance } from 'axios';

export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

// Access token stored in memory only — never in localStorage — to prevent XSS token theft.
// Survives SPA navigation; lost on hard refresh, which triggers the refresh-token flow in authStore.
let _accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

export function getAccessToken(): string | null {
  return _accessToken;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) {
        _accessToken = null;
        document.cookie = 'auth_token=; path=/; max-age=0';
        window.location.href = '/login';
        return Promise.reject(error);
      }

      try {
        const response = await axios.post(
          `${API_URL}/auth/refresh`,
          {},
          {
            withCredentials: true,
            headers: { Authorization: `Bearer ${refreshToken}` },
          }
        );
        // Backend sets the HttpOnly auth_token cookie via Set-Cookie — no client-side cookie write.
        const newToken = response.data.access_token;
        _accessToken = newToken;
        return apiClient(originalRequest);
      } catch (refreshError: unknown) {
        const status = (refreshError as { response?: { status?: number } })?.response?.status;
        if (status === 401 || status === 403) {
          // Refresh token expired or invalid — clear everything and redirect
          _accessToken = null;
          localStorage.removeItem('refresh_token');
          window.location.href = '/login';
        }
        // Network/server errors — keep refresh token for next page load
        return Promise.reject(refreshError);
      }
    }

    if (error.response?.status >= 500) {
      console.error(
        `[API] ${error.response.status} ${error.config?.method?.toUpperCase()} ${error.config?.url}`,
        error.response.data
      );
    }

    return Promise.reject(error);
  }
);

export default apiClient;
