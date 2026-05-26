/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // ── Claude 官方配色体系 ──
        // 主背景
        canvas: '#1a1614',
        // 卡片/侧边栏背景
        slate: '#2b2522',
        // 主强调色 — Claude 暖橙
        accent: '#d97757',
        // 次强调色 — 暖棕
        'accent-warm': '#c4956a',
        // 品牌色 — Claude 铜橙（主按钮、高亮）
        brand: '#d97757',
        // 淡品牌色 — 悬浮/选中背景
        'brand-muted': '#d9775720',
        // 信息色 — 蓝调
        info: '#6b8aed',
        // 成功色
        success: '#6db88f',
        // 警告色
        warning: '#d4a843',
        // 危险色
        danger: '#d45d5d',
        // 边框
        border: '#3d3632',
        'border-subtle': '#2e2824',
        // 文字层级
        'text-primary': '#ede8e3',
        'text-secondary': '#a89e95',
        'text-muted': '#6e6560',
        // 保留旧色名兼容（映射到新色值）
        mint: '#d97757',
        violet: '#8b6cef',
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
