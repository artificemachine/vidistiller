'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { type ThemeId, DEFAULT_THEME, STORAGE_KEYS } from '@/lib/themes';

type Mode = 'light' | 'dark';

interface ThemeContextValue {
  theme: Mode;
  toggleTheme: () => void;
  themeId: ThemeId;
  setThemeId: (id: ThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Mode>('dark');
  const [themeId, setThemeIdState] = useState<ThemeId>(DEFAULT_THEME);

  useEffect(() => {
    try {
      const storedMode = localStorage.getItem(STORAGE_KEYS.mode) as Mode | null;
      const prefersDark = typeof window.matchMedia === 'function'
        && window.matchMedia('(prefers-color-scheme: dark)').matches;
      const initialMode = storedMode || (prefersDark ? 'dark' : 'light');
      setTheme(initialMode);
      document.documentElement.classList.toggle('dark', initialMode === 'dark');

      const storedTheme = localStorage.getItem(STORAGE_KEYS.theme) as ThemeId | null;
      if (storedTheme) {
        setThemeIdState(storedTheme);
        document.documentElement.setAttribute('data-theme', storedTheme);
      }
    } catch {
      // SSR or test environment without localStorage
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try { localStorage.setItem(STORAGE_KEYS.mode, next); } catch { /* noop */ }
    document.documentElement.classList.toggle('dark', next === 'dark');
  };

  const setThemeId = (id: ThemeId) => {
    setThemeIdState(id);
    try { localStorage.setItem(STORAGE_KEYS.theme, id); } catch { /* noop */ }
    document.documentElement.setAttribute('data-theme', id);
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, themeId, setThemeId }}>
      {children}
    </ThemeContext.Provider>
  );
}
