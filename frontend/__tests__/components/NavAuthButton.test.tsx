import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

vi.mock('@/components/NavStatusBadge', () => ({
  default: () => <span data-testid="nav-status-badge" />,
}));

const mockLogout = vi.fn();

vi.mock('@/lib/authStore', () => ({
  useAuthStore: vi.fn(),
}));

import { useAuthStore } from '@/lib/authStore';
import NavAuthButton from '@/components/NavAuthButton';
import ThemeProvider from '@/components/ThemeProvider';

const SETUPS_KEY = 'youtube-model-feeder-ui-setups';

function renderWithProviders(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

function mockAuth(overrides = {}) {
  (useAuthStore as any).mockReturnValue({
    user: { username: 'testuser' },
    isAuthenticated: true,
    isLoading: false,
    logout: mockLogout,
    ...overrides,
  });
}

function createLocalStorageMock() {
  const store: Record<string, string> = {};
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

let lsMock: ReturnType<typeof createLocalStorageMock>;

beforeEach(() => {
  vi.clearAllMocks();
  lsMock = createLocalStorageMock();
  vi.stubGlobal('localStorage', lsMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('NavAuthButton', () => {
  describe('unauthenticated', () => {
    it('renders login link when not authenticated', () => {
      (useAuthStore as any).mockReturnValue({ user: null, isAuthenticated: false, isLoading: false, logout: vi.fn() });
      renderWithProviders(<NavAuthButton />);
      expect(screen.getByText('login')).toBeInTheDocument();
    });

    it('renders loading indicator while auth is loading', () => {
      (useAuthStore as any).mockReturnValue({ user: null, isAuthenticated: false, isLoading: true, logout: vi.fn() });
      const { container } = renderWithProviders(<NavAuthButton />);
      expect(container.textContent).toContain('...');
    });
  });

  describe('authenticated', () => {
    beforeEach(() => mockAuth());

    it('renders username with dropdown arrow', () => {
      renderWithProviders(<NavAuthButton />);
      expect(screen.getByText('testuser')).toBeInTheDocument();
    });

    it('renders dashboard link', () => {
      renderWithProviders(<NavAuthButton />);
      expect(screen.getByText('dashboard')).toBeInTheDocument();
    });

    it('does not show dropdown by default', () => {
      renderWithProviders(<NavAuthButton />);
      expect(screen.queryByText('settings')).not.toBeInTheDocument();
    });

    it('opens dropdown when username is clicked', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      expect(screen.getByText('settings')).toBeInTheDocument();
      expect(screen.getByText('save ui setup')).toBeInTheDocument();
      expect(screen.getByText('load ui setup')).toBeInTheDocument();
      expect(screen.getByText('logout')).toBeInTheDocument();
    });

    it('closes dropdown on outside click', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      expect(screen.getByText('settings')).toBeInTheDocument();
      await user.click(document.body);
      await waitFor(() => expect(screen.queryByText('settings')).not.toBeInTheDocument());
    });

    it('calls logout and redirects when logout is clicked', async () => {
      const user = userEvent.setup();
      const assignSpy = vi.spyOn(window, 'location', 'get').mockReturnValue({ href: '' } as any);
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('logout'));
      expect(mockLogout).toHaveBeenCalledOnce();
      assignSpy.mockRestore();
    });

    it('clears theme and workspace state from localStorage on logout', async () => {
      const user = userEvent.setup();
      lsMock.setItem('youtube-model-feeder-theme', 'monokai');
      lsMock.setItem('theme', 'dark');
      lsMock.setItem('youtube-model-feeder-workspace-state', '{"playerZoom":80}');

      Object.defineProperty(window, 'location', { value: { href: '' }, writable: true });
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('logout'));

      expect(lsMock.getItem('youtube-model-feeder-theme')).toBeNull();
      expect(lsMock.getItem('theme')).toBeNull();
      expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBeNull();
    });
  });

  describe('save ui setup', () => {
    beforeEach(() => mockAuth());

    it('shows save input when "save ui setup" is clicked', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      expect(screen.getByPlaceholderText('setup name...')).toBeInTheDocument();
    });

    it('saves a new setup to localStorage', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'my layout');
      await user.click(screen.getByText('save'));
      const setups = JSON.parse(lsMock.getItem(SETUPS_KEY) || '[]');
      expect(setups).toHaveLength(1);
      expect(setups[0].name).toBe('my layout');
    });

    it('saves via Enter key', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'keyboard save{Enter}');
      const setups = JSON.parse(lsMock.getItem(SETUPS_KEY) || '[]');
      expect(setups[0].name).toBe('keyboard save');
    });

    it('enforces max 3 setups', async () => {
      const user = userEvent.setup();
      const existing = [
        { name: 'a', savedAt: new Date().toISOString(), data: {} },
        { name: 'b', savedAt: new Date().toISOString(), data: {} },
        { name: 'c', savedAt: new Date().toISOString(), data: {} },
      ];
      lsMock.setItem(SETUPS_KEY, JSON.stringify(existing));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'new{Enter}');

      const setups = JSON.parse(lsMock.getItem(SETUPS_KEY) || '[]');
      expect(setups).toHaveLength(3);
      expect(setups[0].name).toBe('new');
    });

    it('shows overwrite confirmation when name already exists', async () => {
      const user = userEvent.setup();
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'existing', savedAt: new Date().toISOString(), data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'existing');
      await user.click(screen.getByText('save'));

      expect(screen.getByText(/already exists/)).toBeInTheDocument();
      expect(screen.getByText('overwrite')).toBeInTheDocument();
      expect(screen.getByText('cancel')).toBeInTheDocument();
    });

    it('overwrites when confirmed', async () => {
      const user = userEvent.setup();
      const savedAt = '2024-01-01T00:00:00.000Z';
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'existing', savedAt, data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'existing');
      await user.click(screen.getByText('save'));
      await user.click(screen.getByText('overwrite'));

      const setups = JSON.parse(lsMock.getItem(SETUPS_KEY) || '[]');
      expect(setups).toHaveLength(1);
      expect(setups[0].name).toBe('existing');
      expect(setups[0].savedAt).not.toBe(savedAt);
    });

    it('cancels overwrite and stays on save view', async () => {
      const user = userEvent.setup();
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'existing', savedAt: new Date().toISOString(), data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'existing');
      await user.click(screen.getByText('save'));
      await user.click(screen.getByText('cancel'));

      expect(screen.getByPlaceholderText('setup name...')).toBeInTheDocument();
      expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    });

    it('clears overwrite prompt when name is changed', async () => {
      const user = userEvent.setup();
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'existing', savedAt: new Date().toISOString(), data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      await user.type(screen.getByPlaceholderText('setup name...'), 'existing');
      await user.click(screen.getByText('save'));
      expect(screen.getByText(/already exists/)).toBeInTheDocument();

      await user.type(screen.getByPlaceholderText('setup name...'), 'x');
      expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    });

    it('navigates back to menu from save view', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('save ui setup'));
      expect(screen.getByPlaceholderText('setup name...')).toBeInTheDocument();
      // Click back arrow (first svg button in save view header)
      const backBtn = screen.getAllByRole('button').find(
        (b) => b.querySelector('path[d="M8 2L4 6l4 4"]')
      );
      await user.click(backBtn!);
      expect(screen.queryByPlaceholderText('setup name...')).not.toBeInTheDocument();
      expect(screen.getByText('save ui setup')).toBeInTheDocument();
    });
  });

  describe('load ui setup', () => {
    beforeEach(() => mockAuth());

    it('shows empty state when no setups saved', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('load ui setup'));
      expect(screen.getByText('no setups saved yet')).toBeInTheDocument();
    });

    it('lists saved setups', async () => {
      const user = userEvent.setup();
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'work layout', savedAt: '2026-01-01T10:00:00.000Z', data: {} },
        { name: 'home layout', savedAt: '2026-01-02T10:00:00.000Z', data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('load ui setup'));
      expect(screen.getByText('work layout')).toBeInTheDocument();
      expect(screen.getByText('home layout')).toBeInTheDocument();
    });

    it('restores snapshot to localStorage when loading a setup', async () => {
      const user = userEvent.setup();
      // Mock window.location.reload to prevent jsdom error
      Object.defineProperty(window, 'location', {
        value: { ...window.location, reload: vi.fn() },
        writable: true,
      });
      const data = { 'youtube-model-feeder-workspace-state': '{"playerZoom":60}' };
      localStorage.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'my setup', savedAt: new Date().toISOString(), data },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('load ui setup'));
      await user.click(screen.getByText('my setup'));

      expect(lsMock.getItem('youtube-model-feeder-workspace-state')).toBe('{"playerZoom":60}');
      expect(lsMock.getItem('youtube-model-feeder-ui-snapshot')).toBe(JSON.stringify(data));
    });

    it('deletes a setup without loading it', async () => {
      const user = userEvent.setup();
      lsMock.setItem(SETUPS_KEY, JSON.stringify([
        { name: 'to delete', savedAt: new Date().toISOString(), data: {} },
        { name: 'keep me', savedAt: new Date().toISOString(), data: {} },
      ]));

      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('load ui setup'));

      // Each row has a delete × button; click the first one
      const deleteButtons = screen.getAllByTitle('delete');
      await user.click(deleteButtons[0]);

      expect(screen.queryByText('to delete')).not.toBeInTheDocument();
      expect(screen.getByText('keep me')).toBeInTheDocument();

      const setups = JSON.parse(lsMock.getItem(SETUPS_KEY) || '[]');
      expect(setups).toHaveLength(1);
      expect(setups[0].name).toBe('keep me');
    });

    it('navigates back to menu from load view', async () => {
      const user = userEvent.setup();
      renderWithProviders(<NavAuthButton />);
      await user.click(screen.getByText('testuser'));
      await user.click(screen.getByText('load ui setup'));
      expect(screen.getByText('load ui setup', { selector: 'span' })).toBeInTheDocument();

      const backBtn = screen.getAllByRole('button').find(
        (b) => b.querySelector('path[d="M8 2L4 6l4 4"]')
      );
      await user.click(backBtn!);
      expect(screen.getByText('load ui setup', { selector: 'button' })).toBeInTheDocument();
    });
  });
});
