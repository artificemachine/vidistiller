/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './pages/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: 'rgb(var(--color-primary) / <alpha-value>)',
        secondary: 'rgb(var(--color-bg-light) / <alpha-value>)',
        'bg-light': 'rgb(var(--color-bg-light) / <alpha-value>)',
        'bg-dark': 'rgb(var(--color-bg-dark) / <alpha-value>)',
        'card-light': 'rgb(var(--color-card-light) / <alpha-value>)',
        'card-dark': 'rgb(var(--color-card-dark) / <alpha-value>)',
        'text-dark': 'rgb(var(--color-text-dark) / <alpha-value>)',
        'text-light': 'rgb(var(--color-text-light) / <alpha-value>)',
        'text-muted': 'rgb(var(--color-text-muted) / <alpha-value>)',
        'border-light': 'rgb(var(--color-border-light) / <alpha-value>)',
        'border-dark': 'rgb(var(--color-border-dark) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        'input-bg': 'rgb(var(--color-input-bg) / <alpha-value>)',
        'accent-orange': 'rgb(var(--color-accent-orange) / <alpha-value>)',
        'accent-submit': 'rgb(var(--color-accent-submit) / <alpha-value>)',
        // Status colors (not theme-dependent)
        success: '#22C55E',
        warning: '#FFB547',
        destructive: '#FF5C33',
        info: '#0066FF',
      },
      fontFamily: {
        sans: ['Arial', 'Helvetica', 'sans-serif'],
        mono: ["'Fira Code'", 'monospace'],
      },
      borderRadius: {
        '16': '16px',
      },
    },
  },
  plugins: [],
};
