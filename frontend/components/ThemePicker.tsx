'use client';

import { useState, useRef, useEffect } from 'react';
import { useTheme } from './ThemeProvider';
import { THEMES } from '@/lib/themes';

export default function ThemePicker() {
  const { themeId, setThemeId } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="text-text-dark/70 hover:text-text-dark dark:text-text-light/70 dark:hover:text-text-light transition-colors"
      >
        themes
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-44 bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark rounded-lg shadow-lg dark:shadow-gray-900 py-1 z-50">
          {THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => { setThemeId(t.id); setOpen(false); }}
              className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors ${
                themeId === t.id
                  ? 'text-primary'
                  : 'text-text-dark/70 dark:text-text-light/70 hover:text-text-dark dark:hover:text-text-light'
              } hover:bg-bg-light dark:hover:bg-bg-dark`}
            >
              <span
                className="inline-block w-3 h-3 rounded-full shrink-0"
                style={{ backgroundColor: t.primaryColor }}
              />
              {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
