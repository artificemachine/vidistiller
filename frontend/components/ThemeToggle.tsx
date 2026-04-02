'use client';

import { useTheme } from './ThemeProvider';

interface ThemeToggleProps {
  compact?: boolean;
}

export default function ThemeToggle({ compact }: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      className={
        compact
          ? 'p-2 rounded text-gray-400 hover:text-white transition-colors'
          : 'p-1.5 rounded-lg text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors'
      }
      title={theme === 'dark' ? 'switch to light mode' : 'switch to dark mode'}
    >
      {theme === 'dark' ? (
        /* Sun icon */
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="10" cy="10" r="3.5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M10 3V1M10 19v-2M17 10h2M1 10h2M15.07 4.93l1.41-1.41M3.52 16.48l1.41-1.41M15.07 15.07l1.41 1.41M3.52 3.52l1.41 1.41" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      ) : (
        /* Moon icon */
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M17.39 12.03A7.5 7.5 0 017.97 2.61a7.5 7.5 0 109.42 9.42z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}
