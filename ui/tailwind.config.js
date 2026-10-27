/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  darkMode: 'class',
  theme: {
    container: { center: true, padding: '1rem' },
    extend: {
      colors: {
        background: { DEFAULT: 'var(--background)' },
        foreground: { DEFAULT: 'var(--foreground)' },
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--primary-foreground)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--secondary-foreground)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--accent-foreground)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        border: { DEFAULT: 'var(--border)' },
        input: { DEFAULT: 'var(--input)' },
        ring: { DEFAULT: 'var(--ring)' },
        success: { DEFAULT: 'var(--success)', foreground: 'var(--success-foreground)' },
        warning: { DEFAULT: 'var(--warning)', foreground: 'var(--warning-foreground)' },
        destructive: { DEFAULT: 'var(--destructive)', foreground: 'var(--destructive-foreground)' },
        info: { DEFAULT: 'var(--info)', foreground: 'var(--info-foreground)' },
        navy: { DEFAULT: 'var(--navy)', 2: 'var(--navy-2)', 3: 'var(--navy-3)' },
        teal: { DEFAULT: 'var(--teal)' },
        cyan: { DEFAULT: 'var(--cyan)' },
        down: { DEFAULT: 'var(--down)' },
        metal: { 1: 'var(--metal-1)', 2: 'var(--metal-2)', 3: 'var(--metal-3)', hi: 'var(--metal-hi)' },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: ['var(--font-ibm-plex-sans)', 'sans-serif'],
        mono: ['var(--font-ibm-plex-mono)', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(11,18,32,0.05), 0 4px 14px rgba(11,18,32,0.05)',
        pop: '0 10px 30px rgba(11,18,32,0.22)',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};