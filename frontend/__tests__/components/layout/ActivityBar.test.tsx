import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ActivityBar from '@/components/layout/ActivityBar';
import ThemeProvider from '@/components/ThemeProvider';

function renderWithProviders(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

/** Find ActivityBar toggle button by its title attribute. */
function getToggleButton(tooltipText: string): HTMLElement {
  return screen.getByTitle(tooltipText);
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
    expect(getToggleButton('toggle transcript')).toBeInTheDocument();
    expect(getToggleButton('toggle snapshots')).toBeInTheDocument();
    expect(getToggleButton('toggle logs')).toBeInTheDocument();
    // Theme toggle button is also present
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(4);
  });

  it('calls onToggleSidebar when sidebar button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleSidebar = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleSidebar={onToggleSidebar} />);

    await user.click(getToggleButton('toggle transcript'));
    expect(onToggleSidebar).toHaveBeenCalledOnce();
  });

  it('calls onToggleBottom when snapshots button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleBottom = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleBottom={onToggleBottom} />);

    await user.click(getToggleButton('toggle snapshots'));
    expect(onToggleBottom).toHaveBeenCalledOnce();
  });

  it('calls onToggleLogs when logs button is clicked', async () => {
    const user = userEvent.setup();
    const onToggleLogs = vi.fn();
    renderWithProviders(<ActivityBar {...defaultProps} onToggleLogs={onToggleLogs} />);

    await user.click(getToggleButton('toggle logs'));
    expect(onToggleLogs).toHaveBeenCalledOnce();
  });

  it('applies active style when sidebar is visible', () => {
    renderWithProviders(<ActivityBar {...defaultProps} sidebarVisible={true} />);
    const btn = getToggleButton('toggle transcript');
    expect(btn.className).toContain('bg-border-dark');
  });

  it('applies inactive style when sidebar is hidden', () => {
    renderWithProviders(<ActivityBar {...defaultProps} sidebarVisible={false} />);
    const btn = getToggleButton('toggle transcript');
    expect(btn.className).toContain('text-text-light/40');
    expect(btn.className).not.toContain('bg-border-dark');
  });

  it('applies active style when logs are visible', () => {
    renderWithProviders(<ActivityBar {...defaultProps} logsVisible={true} />);
    const btn = getToggleButton('toggle logs');
    expect(btn.className).toContain('bg-border-dark');
  });

  it('applies inactive style when logs are hidden', () => {
    renderWithProviders(<ActivityBar {...defaultProps} logsVisible={false} />);
    const btn = getToggleButton('toggle logs');
    expect(btn.className).toContain('text-text-light/40');
    expect(btn.className).not.toContain('bg-border-dark');
  });
});
