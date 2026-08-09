/** @type {import('tailwindcss').Config} */
// Structural pattern adapted from Claude-Code-Agent-Monitor's client/tailwind.config.js
// (github.com/hoangsonww/Claude-Code-Agent-Monitor, MIT, (c) Son Nguyen) - see README credit.
// UNLIKE that source, every color below is a CSS custom property, not a literal hex: the same
// Tailwind utility classes (bg-surface-2, border-border, text-accent, ...) theme-switch
// automatically via src/index.css's `@media (prefers-color-scheme: dark)` block, because the
// underlying `--surface-*`/`--border*`/`--accent*` variables are redefined there. This keeps our
// existing light mode (the source repo has none) while porting the elevation-ramp shape.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          0: 'var(--surface-0)',
          1: 'var(--surface-1)',
          2: 'var(--surface-2)',
          3: 'var(--surface-3)',
          4: 'var(--surface-4)',
          5: 'var(--surface-5)',
        },
        border: {
          DEFAULT: 'var(--border)',
          strong: 'var(--border-strong)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          muted: 'var(--accent-muted)',
        },
        fg: 'var(--fg)',
        muted: 'var(--muted)',
        ok: 'var(--ok)',
        bad: 'var(--bad)',
        warn: 'var(--warn)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
      },
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
