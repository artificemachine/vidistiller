import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { GET } from '@/app/snapproxy/[...path]/route';

/**
 * The proxy sits in front of an authenticated, ownership-checked backend
 * route. If it ever forwards a request without the caller's credentials it
 * becomes an anonymous read hole around that check.
 */

function makeRequest(cookie?: string) {
  return {
    cookies: {
      get: (name: string) =>
        cookie && name === 'auth_token' ? { value: cookie } : undefined,
    },
  } as any;
}

const params = (path: string[]) => ({ params: Promise.resolve({ path }) });

describe('snapproxy route', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(new ArrayBuffer(4), {
        status: 200,
        headers: { 'content-type': 'image/jpeg' },
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('rejects a request with no auth cookie', async () => {
    const res = await GET(makeRequest(), params(['static', 'snapshots', 'job1', 'f.jpg']));
    expect(res.status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('forwards the auth cookie as a bearer token', async () => {
    const res = await GET(
      makeRequest('tok123'),
      params(['static', 'snapshots', 'job1', 'f.jpg']),
    );
    expect(res.status).toBe(200);
    const [, init] = (fetch as any).mock.calls[0];
    expect(init.headers.Authorization).toBe('Bearer tok123');
  });

  it('does not allow a shared cache to hold per-user media', async () => {
    const res = await GET(
      makeRequest('tok123'),
      params(['static', 'snapshots', 'job1', 'f.jpg']),
    );
    expect(res.headers.get('Cache-Control')).toContain('private');
    expect(res.headers.get('Cache-Control')).not.toContain('public');
  });

  it('rejects traversal segments before any upstream call', async () => {
    const res = await GET(makeRequest('tok123'), params(['static', 'snapshots', '..', 'f.jpg']));
    expect(res.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('refuses paths outside the snapshots prefix', async () => {
    const res = await GET(makeRequest('tok123'), params(['etc', 'passwd']));
    expect(res.status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
  });
});
