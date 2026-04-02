import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock react-resizable-panels since it requires full browser APIs (ResizeObserver, localStorage)
vi.mock('react-resizable-panels', () => ({
  Group: ({ children }: any) => <div data-testid="panel-group">{children}</div>,
  Panel: ({ children }: any) => <div data-testid="panel">{children}</div>,
  Separator: ({ children }: any) => <div data-testid="separator">{children}</div>,
  usePanelRef: () => ({ current: null }),
  useDefaultLayout: () => ({
    defaultLayout: undefined,
    onLayoutChange: vi.fn(),
    onLayoutChanged: vi.fn(),
  }),
}));

import WorkspaceLayout from '@/components/layout/WorkspaceLayout';
import ThemeProvider from '@/components/ThemeProvider';

function renderWithProviders(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
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

describe('WorkspaceLayout', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createLocalStorageMock());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders sidebar content', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>Sidebar Content</div>}
        main={() => <div>Main Content</div>}
        bottom={<div>Bottom Content</div>}
      />
    );
    expect(screen.getByText('Sidebar Content')).toBeInTheDocument();
  });

  it('renders main content', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>Sidebar</div>}
        main={() => <div>Main Content</div>}
        bottom={<div>Bottom</div>}
      />
    );
    expect(screen.getByText('Main Content')).toBeInTheDocument();
  });

  it('renders bottom content', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>Sidebar</div>}
        main={() => <div>Main</div>}
        bottom={<div>Bottom Content</div>}
      />
    );
    expect(screen.getByText('Bottom Content')).toBeInTheDocument();
  });

  it('renders panel headers', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>S</div>}
        main={() => <div>M</div>}
        bottom={<div>B</div>}
      />
    );
    expect(screen.getByText('transcript')).toBeInTheDocument();
    expect(screen.getByText('player')).toBeInTheDocument();
    expect(screen.getByText('processing logs')).toBeInTheDocument();
  });

  it('renders activity bar with toggle buttons', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>S</div>}
        main={() => <div>M</div>}
        bottom={<div>B</div>}
      />
    );
    expect(screen.getByTitle('toggle transcript')).toBeInTheDocument();
    expect(screen.getByTitle('toggle snapshots')).toBeInTheDocument();
  });

  it('renders logs panel when logs prop is provided', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>S</div>}
        main={() => <div>M</div>}
        logs={<div>Logs Content</div>}
        bottom={<div>B</div>}
      />
    );
    expect(screen.getByText('snapshots')).toBeInTheDocument();
    expect(screen.getByText('Logs Content')).toBeInTheDocument();
  });

  it('does not render snapshots panel header when logs prop is omitted', () => {
    renderWithProviders(
      <WorkspaceLayout
        sidebar={<div>S</div>}
        main={() => <div>M</div>}
        bottom={<div>B</div>}
      />
    );
    expect(screen.queryByText('snapshots')).not.toBeInTheDocument();
    expect(screen.getByText('processing logs')).toBeInTheDocument();
  });

  it('renders zoom slider with correct range, step, and default value', () => {
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('min', '10');
    expect(slider).toHaveAttribute('max', '100');
    expect(slider).toHaveAttribute('step', '1');
    expect(slider).toHaveAttribute('value', '40');
  });

  it('renders zoom −, + and reset buttons', () => {
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    expect(screen.getByTitle('zoom out')).toBeInTheDocument();
    expect(screen.getByTitle('zoom in')).toBeInTheDocument();
    expect(screen.getByTitle('reset zoom')).toBeInTheDocument();
  });

  it('zoom − decrements and + increments by 1', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '40'));
    await user.click(screen.getByTitle('zoom out'));
    expect(screen.getByRole('slider')).toHaveAttribute('value', '39');
    await user.click(screen.getByTitle('zoom in'));
    expect(screen.getByRole('slider')).toHaveAttribute('value', '40');
  });

  it('reset zoom button restores to 40', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '40'));
    await user.click(screen.getByTitle('zoom out'));
    await user.click(screen.getByTitle('zoom out'));
    expect(screen.getByRole('slider')).toHaveAttribute('value', '38');
    await user.click(screen.getByTitle('reset zoom'));
    expect(screen.getByRole('slider')).toHaveAttribute('value', '40');
  });

  it('zoom − clamps at minimum 10', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('localStorage', createLocalStorageMock({ 'youtube-model-feeder-workspace-state': '{"playerZoom":10}' }));
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    // Wait for hydration to apply saved zoom
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '10'));
    await user.click(screen.getByTitle('zoom out'));
    expect(Number(screen.getByRole('slider').getAttribute('value'))).toBeGreaterThanOrEqual(10);
  });

  it('zoom + clamps at maximum 100', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('localStorage', createLocalStorageMock({ 'youtube-model-feeder-workspace-state': '{"playerZoom":100}' }));
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '100'));
    await user.click(screen.getByTitle('zoom in'));
    expect(Number(screen.getByRole('slider').getAttribute('value'))).toBeLessThanOrEqual(100);
  });

  it('persists UI state to localStorage when zoom changes', async () => {
    const lsMock = createLocalStorageMock();
    vi.stubGlobal('localStorage', lsMock);
    const user = userEvent.setup();
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    // Wait for hydration, then interact
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '40'));
    await user.click(screen.getByTitle('zoom in'));
    const state = JSON.parse(lsMock.getItem('youtube-model-feeder-workspace-state') || '{}');
    expect(state.playerZoom).toBe(41);
  });

  it('restores zoom from localStorage on mount', async () => {
    vi.stubGlobal('localStorage', createLocalStorageMock({ 'youtube-model-feeder-workspace-state': '{"playerZoom":75}' }));
    renderWithProviders(
      <WorkspaceLayout sidebar={<div>S</div>} main={() => <div>M</div>} bottom={<div>B</div>} />
    );
    await vi.waitFor(() => expect(screen.getByRole('slider')).toHaveAttribute('value', '75'));
  });
});
