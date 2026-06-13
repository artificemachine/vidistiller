import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ActivityBar from '@/components/layout/ActivityBar';
import ThemeProvider from '@/components/ThemeProvider';

function renderWithProviders(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

/** Find ActivityBar toggle button by its aria-label. */
function getToggleButton(label: string): HTMLElement {
  return screen.getByRole('button', { name: label });
}

describe('ActivityBar', () => {
  const defaultProps = {
    sidebarVisible: true,
    bottomVisible: true,
    logsVisible: true,
    onToggleSidebar: vi.fn(),
    onToggleBottom: vi.fn(),
    onToggleLogs: vi.fn(),
  };

  it('renders toggle buttons and theme toggle', () => {
    renderWithProviders(<ActivityBar {...defaultProps} />);
    expect(getToggleButton('Transcript')).toBeInTheDocument();
    expect(getToggleButton('Snapshots')).toBeInTheDocument();
    expect(getToggleButton('Logs')).toBeInTheDocument();
    // Theme toggle + save layout button also present
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(5);
  });

  it('calls onToggleSidebar when sidebar button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleSidebar = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleSidebar={onToggleSidebar} />);

    await user.click(getToggleButton('Transcript'));
    expect(onToggleSidebar).toHaveBeenCalledOnce();
  });

  it('calls onToggleBottom when snapshots button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleBottom = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleBottom={onToggleBottom} />);

    await user.click(getToggleButton('Snapshots'));
    expect(onToggleBottom).toHaveBeenCalledOnce();
  });

  it('calls onToggleLogs when logs button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleLogs = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleLogs={onToggleLogs} />);

    await user.click(getToggleButton('Logs'));
    expect(onToggleLogs).toHaveBeenCalledOnce();
  });

  it('applies active style when sidebar is visible', () => {
    renderWithProviders(<ActivityBar {...defaultProps} sidebarVisible={true} />);
    const btn = getToggleButton('Transcript');
    expect(btn.className).toContain('bg-border-dark');
  });

  it('applies inactive style when sidebar is hidden', () => {
    renderWithProviders(<ActivityBar {...defaultProps} sidebarVisible={false} />);
    const btn = getToggleButton('Transcript');
    expect(btn.className).toContain('text-text-light/40');
    expect(btn.className).not.toContain('bg-border-dark');
  });

  it('applies active style when logs are visible', () => {
    renderWithProviders(<ActivityBar {...defaultProps} logsVisible={true} />);
    const btn = getToggleButton('Logs');
    expect(btn.className).toContain('bg-border-dark');
  });

  it('applies inactive style when logs are hidden', () => {
    renderWithProviders(<ActivityBar {...defaultProps} logsVisible={false} />);
    const btn = getToggleButton('Logs');
    expect(btn.className).toContain('text-text-light/40');
    expect(btn.className).not.toContain('bg-border-dark');
  });
});
