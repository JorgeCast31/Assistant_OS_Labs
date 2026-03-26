import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        os: {
          base:        '#0c0d11',
          surface:     '#12141b',
          elevated:    '#1a1c25',
          border:      '#252835',
          'border-hi': '#323548',
        },
        tx: {
          primary:   '#dde1f0',
          secondary: '#8b90a6',
          muted:     '#4b5066',
        },
        accent: {
          DEFAULT: '#5b9cf6',
          dim:     '#243a5e',
          glow:    '#7ab3ff',
        },
        ok:   '#22c55e',
        warn: '#eab308',
        err:  '#ef4444',
        idle: '#4b5066',
      },
      fontFamily: {
        mono: [
          'JetBrains Mono', 'Fira Code', 'Cascadia Code',
          'ui-monospace', 'SFMono-Regular', 'monospace',
        ],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
      },
    },
  },
  plugins: [],
}

export default config
