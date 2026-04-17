export type ThemeId = 'lunaris' | 'monokai' | 'nord';

export interface ThemeOption {
  id: ThemeId;
  label: string;
  primaryColor: string;
}

export const THEMES: ThemeOption[] = [
  { id: 'lunaris', label: 'lunaris', primaryColor: '#FF8400' },
  { id: 'monokai', label: 'monokai', primaryColor: '#A6E22E' },
  { id: 'nord', label: 'nord', primaryColor: '#88C0D0' },
];

export const DEFAULT_THEME: ThemeId = 'lunaris';

export const STORAGE_KEYS = {
  theme: 'vidistiller-theme',
  mode: 'theme',
} as const;
