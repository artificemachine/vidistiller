import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mockGet, mockPost, mockAxiosPost, mockSetAccessToken } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn().mockResolvedValue({}),
  mockAxiosPost: vi.fn(),
  mockSetAccessToken: vi.fn(),
}));

// Access token is in-memory; the store calls setAccessToken() from api.ts, not localStorage.
vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost },
  apiClient: { get: mockGet, post: mockPost },
  setAccessToken: mockSetAccessToken,
  API_URL: 'http://localhost:8000/api',
}));

vi.mock('axios', () => ({
  default: { post: mockAxiosPost },
}));

import { useAuthStore } from '@/lib/authStore';

const mockUser = {
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  is_active: true,
};

function createLocalStorageMock() {
  const store = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => store.set(key, value)),
    removeItem: vi.fn((key: string) => store.delete(key)),
    clear: vi.fn(() => store.clear()),
    get length() { return store.size; },
    key: vi.fn((i: number) => [...store.keys()][i] ?? null),
  };
}

describe('authStore', () => {
  let storage: ReturnType<typeof createLocalStorageMock>;

  beforeEach(() => {
    vi.clearAllMocks();
    storage = createLocalStorageMock();
    vi.stubGlobal('localStorage', storage);
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('setUser', () => {
    it('sets user and marks authenticated', () => {
      useAuthStore.getState().setUser(mockUser);
      const state = useAuthStore.getState();
      expect(state.user).toEqual(mockUser);
      expect(state.isAuthenticated).toBe(true);
    });

    it('clears user and marks unauthenticated when null', () => {
      useAuthStore.getState().setUser(mockUser);
      useAuthStore.getState().setUser(null);
      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe('logout', () => {
    it('clears refresh token from localStorage', () => {
      storage.setItem('refresh_token', 'rt');
      useAuthStore.getState().logout();
      expect(storage.removeItem).toHaveBeenCalledWith('refresh_token');
      expect(storage.getItem('refresh_token')).toBeNull();
    });

    it('clears in-memory access token via setAccessToken', () => {
      useAuthStore.getState().logout();
      expect(mockSetAccessToken).toHaveBeenCalledWith(null);
    });

    it('fires backend logout request to clear HttpOnly cookie', () => {
      useAuthStore.getState().logout();
      // Fire-and-forget — just verify it was called
      expect(mockPost).toHaveBeenCalledWith('/auth/logout');
    });

    it('resets store state', () => {
      useAuthStore.getState().setUser(mockUser);
      useAuthStore.getState().logout();
      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
    });
  });

  describe('initialize', () => {
    it('sets unauthenticated when no refresh token exists', async () => {
      await useAuthStore.getState().initialize();
      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });

    it('makes no network calls when no refresh token', async () => {
      await useAuthStore.getState().initialize();
      expect(mockAxiosPost).not.toHaveBeenCalled();
      expect(mockGet).not.toHaveBeenCalled();
    });

    it('refreshes token when refresh token exists, then fetches user', async () => {
      storage.setItem('refresh_token', 'valid-refresh');
      mockAxiosPost.mockResolvedValueOnce({
        data: { access_token: 'new-access-token' },
      });
      mockGet.mockResolvedValueOnce({ data: mockUser });

      await useAuthStore.getState().initialize();
      const state = useAuthStore.getState();

      expect(mockAxiosPost).toHaveBeenCalledWith(
        expect.stringContaining('/auth/refresh'),
        {},
        { headers: { Authorization: 'Bearer valid-refresh' } }
      );
      // Access token is stored in memory via setAccessToken, not localStorage
      expect(mockSetAccessToken).toHaveBeenCalledWith('new-access-token');
      expect(state.user).toEqual(mockUser);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isLoading).toBe(false);
    });

    it('stores rotated refresh token when server returns one', async () => {
      storage.setItem('refresh_token', 'old-refresh');
      mockAxiosPost.mockResolvedValueOnce({
        data: { access_token: 'new-at', refresh_token: 'new-refresh' },
      });
      mockGet.mockResolvedValueOnce({ data: mockUser });

      await useAuthStore.getState().initialize();

      expect(storage.setItem).toHaveBeenCalledWith('refresh_token', 'new-refresh');
    });

    it('clears refresh token and sets unauthenticated when refresh fails', async () => {
      storage.setItem('refresh_token', 'expired-refresh');
      mockAxiosPost.mockRejectedValueOnce({ response: { status: 401 } });

      await useAuthStore.getState().initialize();
      const state = useAuthStore.getState();
      expect(storage.removeItem).toHaveBeenCalledWith('refresh_token');
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });

    it('preserves refresh token when /auth/me fails after successful refresh', async () => {
      storage.setItem('refresh_token', 'valid-refresh');
      mockAxiosPost.mockResolvedValueOnce({ data: { access_token: 'token' } });
      mockGet.mockRejectedValueOnce(new Error('Network error'));

      await useAuthStore.getState().initialize();

      // Refresh token preserved — interceptor may recover it on next page load
      expect(storage.removeItem).not.toHaveBeenCalledWith('refresh_token');
      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });

    it('clears in-memory access token when /auth/me fails', async () => {
      storage.setItem('refresh_token', 'valid-refresh');
      mockAxiosPost.mockResolvedValueOnce({ data: { access_token: 'token' } });
      mockGet.mockRejectedValueOnce(new Error('Server error'));

      await useAuthStore.getState().initialize();

      expect(mockSetAccessToken).toHaveBeenLastCalledWith(null);
      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
    });
  });
});
