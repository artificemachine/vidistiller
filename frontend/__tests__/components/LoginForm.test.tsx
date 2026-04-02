import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost },
  apiClient: { get: mockGet, post: mockPost },
  setAccessToken: vi.fn(),
}));

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

import LoginPage from '@/app/login/page';

function renderLogin() {
  return render(<LoginPage />);
}

function createLocalStorageMock(initial: Record<string, string> = {}) {
  const store: Record<string, string> = { ...initial };
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = String(value); },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
    get length() { return Object.keys(store).length; },
    key: (i: number) => Object.keys(store)[i] ?? null,
    _store: store,
  };
}

function mockLoginSuccess() {
  mockPost.mockResolvedValueOnce({ data: { access_token: 'tok', refresh_token: 'ref' } });
  mockGet.mockResolvedValueOnce({ data: { username: 'testuser', id: 1 } });
}

describe('LoginPage error display', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows human-readable validation error message from 422 response', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'password'], msg: 'Field required', type: 'missing' },
          ],
        },
      },
    });

    renderLogin();

    await user.type(screen.getByLabelText(/username/i), 'someone');
    await user.type(screen.getByLabelText(/^password$/i), 'x');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/field required/i)).toBeInTheDocument();
  });

  it('shows authentication error message from 401 response', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 401,
        data: { message: 'Invalid username or password' },
      },
    });

    renderLogin();

    await user.type(screen.getByLabelText(/username/i), 'wronguser');
    await user.type(screen.getByLabelText(/^password$/i), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/invalid username or password/i)).toBeInTheDocument();
  });

  it('password field is hidden by default', () => {
    renderLogin();
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute('type', 'password');
  });

  it('toggles password visibility when eye icon is clicked', async () => {
    const user = userEvent.setup();
    renderLogin();

    const passwordInput = screen.getByLabelText(/^password$/i);
    const toggleBtn = screen.getByRole('button', { name: /show password/i });

    expect(passwordInput).toHaveAttribute('type', 'password');

    await user.click(toggleBtn);
    expect(passwordInput).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: /hide password/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /hide password/i }));
    expect(passwordInput).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
  });

  it('does not display raw JSON in error output', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'username'], msg: 'Field required', type: 'missing' },
            { loc: ['body', 'password'], msg: 'Field required', type: 'missing' },
          ],
        },
      },
    });

    renderLogin();

    await user.type(screen.getByLabelText(/username/i), 'a');
    await user.type(screen.getByLabelText(/^password$/i), 'b');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await screen.findByText(/field required/i);

    // No raw JSON markers in error display
    const errorDiv = screen.getByText(/field required/i).closest('div');
    expect(errorDiv?.textContent).not.toMatch(/\[\{/);
    expect(errorDiv?.textContent).not.toMatch(/"type":/);
  });
});

describe('LoginPage UI setup restore', () => {
  let lsMock: ReturnType<typeof createLocalStorageMock>;
  let locationHref: string;

  beforeEach(() => {
    vi.clearAllMocks();
    lsMock = createLocalStorageMock();
    vi.stubGlobal('localStorage', lsMock);
    // Mock window.location so jsdom doesn't throw on href assignment
    locationHref = '';
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function loginAs(username = 'testuser') {
    const user = userEvent.setup();
    mockLoginSuccess();
    renderLogin();
    await user.type(screen.getByLabelText(/username/i), username);
    await user.type(screen.getByLabelText(/^password$/i), 'pass');
    await user.click(screen.getByRole('button', { name: /sign in/i }));
    // Wait for navigation (hard nav via window.location.href)
    await vi.waitFor(() => expect(window.location.href).toBe('/dashboard'));
  }

  it('restores last saved UI setup from youtube-model-feeder-ui-setups on login', async () => {
    const data = { 'youtube-model-feeder-workspace-state': '{"playerZoom":75,"sidebarVisible":true}', 'youtube-model-feeder-theme': 'monokai' };
    lsMock.setItem('youtube-model-feeder-ui-setups', JSON.stringify([
      { name: 'my layout', savedAt: new Date().toISOString(), data },
    ]));

    await loginAs();

    expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBe('{"playerZoom":75,"sidebarVisible":true}');
    expect(lsMock.getItem('youtube-model-feeder-theme')).toBe('monokai');
  });

  it('falls back to youtube-model-feeder-ui-snapshot when no named setups exist', async () => {
    const data = { 'youtube-model-feeder-workspace-state': '{"playerZoom":60}' };
    lsMock.setItem('youtube-model-feeder-ui-snapshot', JSON.stringify(data));

    await loginAs();

    expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBe('{"playerZoom":60}');
  });

  it('skips restore gracefully when no setup or snapshot exists', async () => {
    await loginAs();
    expect(window.location.href).toBe('/dashboard');
  });

  it('uses first (most recent) setup from list', async () => {
    lsMock.setItem('youtube-model-feeder-ui-setups', JSON.stringify([
      { name: 'newest', savedAt: '2026-03-01T00:00:00Z', data: { 'youtube-model-feeder-workspace-state': '{"playerZoom":80}' } },
      { name: 'older', savedAt: '2026-01-01T00:00:00Z', data: { 'youtube-model-feeder-workspace-state': '{"playerZoom":30}' } },
    ]));

    await loginAs();

    expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBe('{"playerZoom":80}');
  });

  it('redirects to /dashboard after restoring UI', async () => {
    await loginAs();
    expect(window.location.href).toBe('/dashboard');
  });

  it('removes null-valued keys from localStorage during restore', async () => {
    const data: Record<string, string | null> = {
      'youtube-model-feeder-workspace-state': '{"playerZoom":55}',
      'youtube-model-feeder-theme': null,
    };
    lsMock.setItem('youtube-model-feeder-ui-setups', JSON.stringify([
      { name: 'test', savedAt: new Date().toISOString(), data },
    ]));
    lsMock.setItem('youtube-model-feeder-theme', 'nord');

    await loginAs();

    expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBe('{"playerZoom":55}');
    expect(lsMock.getItem('youtube-model-feeder-theme')).toBeNull();
  });
});
