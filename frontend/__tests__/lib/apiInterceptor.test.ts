import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Tests for the axios response interceptor in lib/api.ts.
 *
 * Strategy: We mock `axios` itself (the module) so that when lib/api.ts
 * calls `axios.create()` and `axios.post()`, we control the behaviour.
 * We then drive the interceptor by triggering error responses through
 * the mocked apiClient.
 */

const { mockAxiosPost, interceptors, mockRequest } = vi.hoisted(() => {
  const requestHandlers: Array<(c: any) => any> = [];
  const responseHandlers: Array<{ onFulfilled: (r: any) => any; onRejected: (e: any) => any }> = [];

  const interceptors = {
    request: {
      use: vi.fn((fn: any) => { requestHandlers.push(fn); }),
      handlers: requestHandlers,
    },
    response: {
      use: vi.fn((onFulfilled: any, onRejected: any) => {
        responseHandlers.push({ onFulfilled, onRejected });
      }),
      handlers: responseHandlers,
    },
  };

  const mockRequest = vi.fn();

  return { mockAxiosPost: vi.fn(), interceptors, mockRequest };
});

vi.mock('axios', () => {
  const createFn = vi.fn(() => {
    const client = Object.assign(mockRequest, {
      interceptors,
      defaults: { headers: { common: {} } },
    });
    return client;
  });
  return {
    default: {
      create: createFn,
      post: mockAxiosPost,
    },
  };
});

/** Create a fresh localStorage stub backed by a real Map. */
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

describe('apiClient interceptor', () => {
  let storage: ReturnType<typeof createLocalStorageMock>;
  let onRejected: (error: any) => Promise<any>;
  let getAccessToken: () => string | null;

  beforeEach(async () => {
    vi.clearAllMocks();
    storage = createLocalStorageMock();
    vi.stubGlobal('localStorage', storage);

    Object.defineProperty(window, 'location', {
      writable: true,
      value: { href: '/' },
    });

    interceptors.request.handlers.length = 0;
    interceptors.response.handlers.length = 0;

    vi.resetModules();
    const mod = await import('@/lib/api');
    getAccessToken = mod.getAccessToken;
    mod.setAccessToken('expired');

    onRejected = interceptors.response.handlers[0]?.onRejected;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function make401(config = {}) {
    return { response: { status: 401 }, config: { _retry: false, ...config } };
  }

  function make500(config = {}) {
    return { response: { status: 500, data: 'err' }, config: { method: 'get', url: '/x', ...config } };
  }

  it('refreshes token on 401 and retries the original request', async () => {
    storage.setItem('refresh_token', 'valid-refresh');

    mockAxiosPost.mockResolvedValueOnce({
      data: { access_token: 'new-token' },
    });
    mockRequest.mockResolvedValueOnce({ data: 'retried' });

    const result = await onRejected(make401());

    expect(mockAxiosPost).toHaveBeenCalledWith(
      expect.stringContaining('/auth/refresh'),
      {},
      { headers: { Authorization: 'Bearer valid-refresh' }, withCredentials: true }
    );
    // Access token is in-memory only (never in localStorage)
    expect(getAccessToken()).toBe('new-token');
    expect(result).toEqual({ data: 'retried' });
  });

  it('redirects to /login when no refresh token on 401', async () => {
    await expect(onRejected(make401())).rejects.toBeTruthy();

    // In-memory access token cleared
    expect(getAccessToken()).toBeNull();
    expect(window.location.href).toBe('/login');
  });

  it('clears all tokens when refresh token is rejected (401)', async () => {
    storage.setItem('refresh_token', 'expired-refresh');

    mockAxiosPost.mockRejectedValueOnce({ response: { status: 401 } });

    await expect(onRejected(make401())).rejects.toBeTruthy();

    expect(getAccessToken()).toBeNull();
    expect(storage.getItem('refresh_token')).toBeNull();
    expect(window.location.href).toBe('/login');
  });

  it('clears all tokens when refresh returns 403', async () => {
    storage.setItem('refresh_token', 'revoked');

    mockAxiosPost.mockRejectedValueOnce({ response: { status: 403 } });

    await expect(onRejected(make401())).rejects.toBeTruthy();

    expect(getAccessToken()).toBeNull();
    expect(storage.getItem('refresh_token')).toBeNull();
    expect(window.location.href).toBe('/login');
  });

  it('keeps refresh token on network error during refresh', async () => {
    storage.setItem('refresh_token', 'valid-refresh');

    mockAxiosPost.mockRejectedValueOnce(new Error('Network Error'));

    await expect(onRejected(make401())).rejects.toThrow('Network Error');

    expect(storage.getItem('refresh_token')).toBe('valid-refresh');
    expect(window.location.href).toBe('/');
  });

  it('keeps refresh token on 500 error during refresh', async () => {
    storage.setItem('refresh_token', 'valid-refresh');

    mockAxiosPost.mockRejectedValueOnce({ response: { status: 500 } });

    await expect(onRejected(make401())).rejects.toBeTruthy();

    expect(storage.getItem('refresh_token')).toBe('valid-refresh');
    expect(window.location.href).toBe('/');
  });

  it('does not attempt refresh on non-401 errors', async () => {
    await expect(onRejected(make500())).rejects.toBeTruthy();
    expect(mockAxiosPost).not.toHaveBeenCalled();
  });

  it('does not retry the same request twice (prevents infinite loop)', async () => {
    storage.setItem('refresh_token', 'valid-refresh');

    const error = { response: { status: 401 }, config: { _retry: true } };

    await expect(onRejected(error)).rejects.toBeTruthy();
    expect(mockAxiosPost).not.toHaveBeenCalled();
  });
});
