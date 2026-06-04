/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // ── KG-Agent 柔和学术配色体系 ──
        // 主背景 - 深灰蓝（GitHub Dark风格）
        canvas: '#0f1419',
        // 卡片/侧边栏背景
        slate: '#1c2128',
        // 品牌色 - 柔和青蓝
        brand: '#58a6ff',
        'brand-muted': '#58a6ff20',
        'brand-warm': '#7c9fcb',
        // 功能色
        info: '#58a6ff',
        success: '#3fb950',
        warning: '#d29922',
        danger: '#f85149',
        // 边框
        border: '#30363d',
        'border-subtle': '#21262d',
        // 文字层级
        'text-primary': '#e6edf3',
        'text-secondary': '#8b949e',
        'text-muted': '#6e7681',
        // 兼容旧色名
        accent: '#58a6ff',
        mint: '#3fb950',
        violet: '#a371f7',
      },
      borderWidth: {
        '0.75': '0.75px',
        '1.5': '1.5px',
        '3': '3px',
      },
      borderRadius: {
        'pill-sm': '20px',
        'pill': '24px',
        'pill-lg': '30px',
        'pill-xl': '40px',
      },
      fontFamily: {
        body: ['"DM Sans"', '"Hanken Grotesk"', 'Helvetica', 'sans-serif'],
        display: ['Impact', 'Helvetica', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Space Mono"', 'Courier New', 'monospace'],
      },
      letterSpacing: {
        label: '1.8px',
        kicker: '1.9px',
        display: '1.07px',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
