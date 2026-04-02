import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ThemeProvider, { useTheme } from '@/components/ThemeProvider';
import { DEFAULT_THEME } from '@/lib/themes';

// Helper component that exposes theme context values for testing
function ThemeConsumer() {
  const { theme, toggleTheme, themeId, setThemeId } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="themeId">{themeId}</span>
      <button onClick={toggleTheme}>Toggle</button>
      <button onClick={() => setThemeId('nord')}>Set Nord</button>
      <button onClick={() => setThemeId('monokai')}>Set Monokai</button>
    </div>
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    // Clean up <html> class and data-theme between tests
    document.documentElement.classList.remove('dark');
    document.documentElement.removeAttribute('data-theme');
    // Reset localStorage mock
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders children', () => {
    render(
      <ThemeProvider>
        <span>child content</span>
      </ThemeProvider>
    );
    expect(screen.getByText('child content')).toBeInTheDocument();
  });

  it('defaults to light theme', () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );
    expect(screen.getByTestId('theme').textContent).toBe('light');
  });

  it('reads stored theme from localStorage', async () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'dark'),
      setItem: vi.fn(),
    });

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );

    // Wait for useEffect to apply
    await act(() => Promise.resolve());
    expect(screen.getByTestId('theme').textContent).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('toggles theme from light to dark', async () => {
    const user = userEvent.setup();
    const setItemMock = vi.fn();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: setItemMock,
    });

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );

    await user.click(screen.getByText('Toggle'));
    expect(screen.getByTestId('theme').textContent).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(setItemMock).toHaveBeenCalledWith('theme', 'dark');
  });

  it('toggles theme from dark back to light', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'dark'),
      setItem: vi.fn(),
    });

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );

    await act(() => Promise.resolve());
    expect(screen.getByTestId('theme').textContent).toBe('dark');

    await user.click(screen.getByText('Toggle'));
    expect(screen.getByTestId('theme').textContent).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('throws when useTheme is used outside ThemeProvider', () => {
    // Suppress console.error for the expected error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<ThemeConsumer />)).toThrow(
      'useTheme must be used within ThemeProvider'
    );
    spy.mockRestore();
  });

  describe('themeId (palette)', () => {
    it('DEFAULT_THEME export is lunaris', () => {
      expect(DEFAULT_THEME).toBe('lunaris');
    });

    it('defaults themeId to lunaris when no youtube-model-feeder-theme in localStorage', async () => {
      render(
        <ThemeProvider>
          <ThemeConsumer />
        </ThemeProvider>
      );
      await act(() => Promise.resolve());
      expect(screen.getByTestId('themeId').textContent).toBe('lunaris');
    });

    it('reads stored youtube-model-feeder-theme from localStorage', async () => {
      vi.stubGlobal('localStorage', {
        getItem: vi.fn((key: string) => key === 'youtube-model-feeder-theme' ? 'nord' : null),
        setItem: vi.fn(),
      });
      render(
        <ThemeProvider>
          <ThemeConsumer />
        </ThemeProvider>
      );
      await act(() => Promise.resolve());
      expect(screen.getByTestId('themeId').textContent).toBe('nord');
      expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
    });

    it('setThemeId updates themeId state and data-theme attribute', async () => {
      const user = userEvent.setup();
      render(
        <ThemeProvider>
          <ThemeConsumer />
        </ThemeProvider>
      );
      await act(() => Promise.resolve());
      expect(screen.getByTestId('themeId').textContent).toBe('lunaris');

      await user.click(screen.getByText('Set Nord'));
      expect(screen.getByTestId('themeId').textContent).toBe('nord');
      expect(document.documentElement.getAttribute('data-theme')).toBe('nord');
    });

    it('setThemeId persists to localStorage', async () => {
      const setItemMock = vi.fn();
      vi.stubGlobal('localStorage', {
        getItem: vi.fn(() => null),
        setItem: setItemMock,
      });
      const user = userEvent.setup();
      render(
        <ThemeProvider>
          <ThemeConsumer />
        </ThemeProvider>
      );
      await act(() => Promise.resolve());
      await user.click(screen.getByText('Set Monokai'));
      expect(setItemMock).toHaveBeenCalledWith('youtube-model-feeder-theme', 'monokai');
    });

    it('setThemeId can switch between palettes', async () => {
      const user = userEvent.setup();
      render(
        <ThemeProvider>
          <ThemeConsumer />
        </ThemeProvider>
      );
      await act(() => Promise.resolve());

      await user.click(screen.getByText('Set Nord'));
      expect(screen.getByTestId('themeId').textContent).toBe('nord');

      await user.click(screen.getByText('Set Monokai'));
      expect(screen.getByTestId('themeId').textContent).toBe('monokai');
      expect(document.documentElement.getAttribute('data-theme')).toBe('monokai');
    });
  });
});
