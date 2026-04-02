import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ThemeProvider from '@/components/ThemeProvider';
import ThemeToggle from '@/components/ThemeToggle';

function renderWithProvider(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark');
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
    });
  });

  it('renders a button', () => {
    renderWithProvider(<ThemeToggle />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('shows "switch to dark mode" title in light mode', () => {
    renderWithProvider(<ThemeToggle />);
    expect(screen.getByTitle('switch to dark mode')).toBeInTheDocument();
  });

  it('switches title after toggling to dark mode', async () => {
    const user = userEvent.setup();
    renderWithProvider(<ThemeToggle />);

    await user.click(screen.getByRole('button'));
    expect(screen.getByTitle('switch to light mode')).toBeInTheDocument();
  });

  it('applies compact class when compact prop is true', () => {
    renderWithProvider(<ThemeToggle compact />);
    const btn = screen.getByRole('button');
    expect(btn.className).toContain('text-gray-400');
    expect(btn.className).toContain('hover:text-white');
  });

  it('applies standard class when compact is false', () => {
    renderWithProvider(<ThemeToggle />);
    const btn = screen.getByRole('button');
    expect(btn.className).toContain('rounded-lg');
    expect(btn.className).not.toContain('hover:text-white');
  });
});
