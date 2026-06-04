# DESIGN.md

> 把复杂的论文阅读、研究选题和证据验证，设计成一个可信、清晰、可继续探索的智能研究工作台。

## 1. Visual Theme & Atmosphere

**Style**: Dark Research Console / 暗色研究工作台  
**Keywords**: 可信、学术、深色、证据透明、层次清晰、轻科技、可探索、产品化  
**Tone**: 面向真实用户的研究产品介绍 — NOT 内部技术文档、流程图堆叠、炫技型赛博页面  
**Feel**: 像一个安静但能力很强的研究助理工作台，用户一打开就知道“我可以把论文和选题交给它处理”。

**Interaction Tier**: L2 流畅交互  
**Dependencies**: CSS + 原生 IntersectionObserver；不默认引入 GSAP/Lenis，保证 GitHub 展示页和 docs 页面轻量稳定。

**Product Narrative**:
- 页面不是罗列“卖点”，而是讲用户真实场景：读论文、找空白、比方法、查证据、沉淀图谱。
- 技术能力作为场景背后的解释出现，不作为第一层叙事。
- 截图和对话示例要让访客一眼看懂：用户问了什么、系统做了什么、证据从哪里来。

**Page Information Architecture**:
1. Hero：一句话定位 + 产品工作台 mockup + 2 个 CTA。
2. Scenario Strip：用 5 个真实场景快速回答“我能用它干什么”。
3. Conversation Demos：对话式示例截图，展示论文助手、研究助手、Self-RAG、证据面板。
4. Research Workflow Story：用用户视角解释“从模糊选题到研究问题”。
5. Evidence Transparency：突出原始证据、来源、支撑状态。
6. Knowledge Graph：展示长期知识沉淀。
7. Mode Guide：不同问题该选什么模式。
8. Closing CTA：开始使用 / 阅读文档 / 查看架构。

## 2. Color Palette & Roles

```css
:root {
  /* Backgrounds */
  --bg: #070A12;
  --bg-alt: #0B1020;
  --surface: rgba(255, 255, 255, 0.045);
  --surface-alt: rgba(255, 255, 255, 0.07);
  --surface-hover: rgba(255, 255, 255, 0.105);
  --surface-strong: #111827;

  /* Borders */
  --border: rgba(148, 163, 184, 0.18);
  --border-hover: rgba(125, 211, 252, 0.42);
  --border-strong: rgba(226, 232, 240, 0.28);

  /* Text */
  --text: #F8FAFC;
  --text-secondary: #CBD5E1;
  --text-tertiary: #94A3B8;
  --text-muted: #64748B;

  /* Accent */
  --accent: #38BDF8;
  --accent-hover: #7DD3FC;
  --accent-strong: #818CF8;
  --accent-soft: rgba(56, 189, 248, 0.12);
  --accent-purple-soft: rgba(129, 140, 248, 0.14);

  /* Semantic */
  --success: #34D399;
  --success-soft: rgba(52, 211, 153, 0.12);
  --warning: #FBBF24;
  --warning-soft: rgba(251, 191, 36, 0.14);
  --error: #FB7185;
  --error-soft: rgba(251, 113, 133, 0.13);

  /* RGB variants for rgba() */
  --bg-rgb: 7, 10, 18;
  --surface-rgb: 255, 255, 255;
  --accent-rgb: 56, 189, 248;
  --accent-strong-rgb: 129, 140, 248;
  --success-rgb: 52, 211, 153;
  --warning-rgb: 251, 191, 36;
  --error-rgb: 251, 113, 133;
}
```

**Color Rules:**
- 所有颜色通过 CSS 变量引用，禁止在页面代码里硬编码 hex。
- 页面主色只使用蓝青到淡紫的科技渐变，不使用高饱和霓虹红绿作为大面积装饰。
- 证据状态使用语义色：绿色表示已支撑，黄色表示部分支撑，红色表示证据不足。
- 背景保持深色，卡片用半透明表面和细边框制造层次。
- 重要截图区域要比周围背景更亮一档，保证 GitHub 页面中可读。

## 3. Typography Rules

**Font Stack:**
```css
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --font-sans: 'Noto Sans SC', 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
}
```

| Role | Font | Size | Weight | Line Height | Letter Spacing |
|------|------|------|--------|-------------|----------------|
| Hero H1 | Noto Sans SC / Inter | clamp(44px, 7vw, 86px) | 800 | 1.05 | -0.04em |
| Hero subtitle | Noto Sans SC / Inter | clamp(17px, 2vw, 22px) | 400 | 1.75 | 0.01em |
| Section H2 | Noto Sans SC / Inter | clamp(30px, 4vw, 52px) | 800 | 1.14 | -0.03em |
| H3 | Noto Sans SC / Inter | 22px-28px | 700 | 1.35 | -0.01em |
| Body | Noto Sans SC / Inter | 16px-18px | 400 | 1.75 | 0.02em |
| Label | JetBrains Mono / Noto Sans SC | 12px-13px | 600 | 1.4 | 0.08em |
| Mono/Code | JetBrains Mono | 13px-15px | 500 | 1.6 | 0 |

**Typography Rules:**
- 中文内容必须优先使用 Noto Sans SC，保证 GitHub 和本地浏览器都可读。
- 长段落行高不低于 1.7，正文不低于 16px。
- Hero 标题可以使用渐变文字，但正文禁止大面积渐变，避免阅读疲劳。
- 代码、路径、模式名和状态标签使用 JetBrains Mono。
- **NEVER use**: Comic Sans、Papyrus、纯英文字体栈、过度装饰字体。

**Text Decoration:**
- Hero h1: 允许一处关键词使用 `linear-gradient(90deg, var(--accent), var(--accent-strong))` 渐变。
- Section h2: 默认纯色，仅在 Evidence / Research 关键章节中允许小范围渐变下划线。
- Body: 禁止渐变、投影和描边。
- Labels: 使用 uppercase / tracking，不使用花哨特效。

## 4. Component Stylings

### Buttons
```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  min-height: 44px;
  padding: 0 1.15rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  font-family: var(--font-sans);
  font-size: 0.94rem;
  font-weight: 700;
  color: var(--text);
  background: var(--surface);
  text-decoration: none;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease, box-shadow 180ms ease;
}

.btn:hover {
  transform: translateY(-2px);
  border-color: var(--border-hover);
  background: var(--surface-hover);
  box-shadow: 0 14px 38px rgba(var(--accent-rgb), 0.16);
}

.btn:active { transform: translateY(0) scale(0.98); }

.btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

.btn:disabled,
.btn[aria-disabled='true'] {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-primary {
  border-color: transparent;
  color: #06111F;
  background: linear-gradient(135deg, var(--accent), var(--accent-strong));
}

.btn-primary:hover {
  background: linear-gradient(135deg, var(--accent-hover), var(--accent-strong));
}
```

### Cards
```css
.card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 24px;
  background: linear-gradient(180deg, var(--surface-alt), var(--surface));
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.24);
  transition: transform 220ms ease, border-color 220ms ease, background 220ms ease, box-shadow 220ms ease;
}

.card::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background: radial-gradient(circle at var(--mx, 50%) var(--my, 0%), rgba(var(--accent-rgb), 0.16), transparent 34%);
  transition: opacity 220ms ease;
}

.card:hover {
  transform: translateY(-4px);
  border-color: var(--border-hover);
  box-shadow: 0 28px 90px rgba(0, 0, 0, 0.32), 0 0 40px rgba(var(--accent-rgb), 0.08);
}

.card:hover::before { opacity: 1; }

.card:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.18);
}
```

### Navigation
```css
.nav {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 68px;
  padding: 0 24px;
  border-bottom: 1px solid transparent;
  background: rgba(var(--bg-rgb), 0.72);
  backdrop-filter: blur(12px);
  transition: border-color 200ms ease, background 200ms ease;
}

.nav.is-scrolled {
  border-color: var(--border);
  background: rgba(var(--bg-rgb), 0.9);
}

.nav-link {
  color: var(--text-tertiary);
  font-size: 0.92rem;
  font-weight: 600;
  text-decoration: none;
  transition: color 160ms ease;
}

.nav-link:hover,
.nav-link:focus-visible { color: var(--text); }
```

### Links
```css
.link {
  color: var(--accent-hover);
  text-decoration: none;
  background-image: linear-gradient(var(--accent-hover), var(--accent-hover));
  background-size: 0% 1px;
  background-repeat: no-repeat;
  background-position: 0 100%;
  transition: color 160ms ease, background-size 180ms ease;
}

.link:hover,
.link:focus-visible {
  color: var(--text);
  background-size: 100% 1px;
}
```

### Tags / Badges
```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 28px;
  padding: 0 0.65rem;
  border-radius: 999px;
  border: 1px solid var(--border);
  color: var(--text-tertiary);
  background: rgba(var(--surface-rgb), 0.045);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.badge-success { color: var(--success); background: var(--success-soft); border-color: rgba(var(--success-rgb), 0.28); }
.badge-warning { color: var(--warning); background: var(--warning-soft); border-color: rgba(var(--warning-rgb), 0.28); }
.badge-error { color: var(--error); background: var(--error-soft); border-color: rgba(var(--error-rgb), 0.28); }
```

### Conversation Mockups
```css
.conversation {
  border: 1px solid var(--border);
  border-radius: 28px;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.92));
  box-shadow: 0 30px 100px rgba(0, 0, 0, 0.35);
}

.message {
  max-width: 82%;
  padding: 14px 16px;
  border-radius: 18px;
  color: var(--text-secondary);
  line-height: 1.72;
}

.message-user {
  margin-left: auto;
  color: var(--text);
  background: linear-gradient(135deg, rgba(var(--accent-rgb), 0.22), rgba(var(--accent-strong-rgb), 0.16));
  border: 1px solid rgba(var(--accent-rgb), 0.3);
}

.message-assistant {
  background: rgba(255, 255, 255, 0.055);
  border: 1px solid var(--border);
}
```

### Evidence Panels
```css
.evidence-item {
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px;
  background: rgba(15, 23, 42, 0.76);
  transition: border-color 180ms ease, background 180ms ease;
}

.evidence-item:hover {
  border-color: var(--border-hover);
  background: rgba(15, 23, 42, 0.95);
}

.evidence-source {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 0.75rem;
}
```

## 5. Layout Principles

**Container:**
- Max width: 1180px
- Wide visual sections: 1280px
- Text-heavy content: 820px
- Horizontal padding: `clamp(20px, 5vw, 48px)`

**Spacing Scale:**
- Hero padding: 96px top / 72px bottom desktop; 64px / 48px mobile
- Section padding: 88px desktop; 56px mobile
- Component gap: 20px-28px
- Card internal padding: 24px-32px desktop; 18px-22px mobile

**Grid:**
```css
.container {
  width: min(1180px, calc(100% - 48px));
  margin-inline: auto;
}

.grid-2 {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 28px;
}

.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}

.bento {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 18px;
}

.bento .span-4 { grid-column: span 4; }
.bento .span-5 { grid-column: span 5; }
.bento .span-7 { grid-column: span 7; }
.bento .span-12 { grid-column: span 12; }

@media (max-width: 860px) {
  .grid-2,
  .grid-3,
  .bento { grid-template-columns: 1fr; }
  .bento > * { grid-column: 1 / -1 !important; }
}
```

**Section Rhythm:**
- Hero 用强视觉截图建立信任。
- 每个场景区块先讲用户问题，再展示系统回答，而不是先讲技术名词。
- 技术架构图只作为后半部分补充，不放在第一屏。

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat | 无阴影，仅边框 | 正文内容、普通列表 |
| Subtle | `0 10px 30px rgba(0,0,0,0.18)` | 小卡片、标签组 |
| Elevated | `0 24px 80px rgba(0,0,0,0.28)` | Demo 截图、对话窗口 |
| Hero | `0 36px 120px rgba(0,0,0,0.42)` + accent glow | 首屏主截图 |
| Glow | `0 0 48px rgba(var(--accent-rgb),0.14)` | 当前路径、证据验证状态 |

**Depth Rules:**
- 阴影只用于表达层级，不用于装饰堆叠。
- 同屏最多一个 Hero 级重阴影对象。
- `backdrop-filter` 不超过 12px，避免滚动卡顿。
- 移动端减少阴影半径，提高性能和可读性。

## 7. Animation & Interaction

**Motion Philosophy**: 动效用于解释产品工作流，不用于炫技。所有动画只使用 opacity、transform、background-position 和 CSS variables。

**Tier**: L2 流畅交互

### Dependencies
```html
<!-- No external animation dependency required. CSS + native IntersectionObserver only. -->
```

### Base Setup
```js
function initScrollReveal(selector = '.reveal', cls = 'in-view') {
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add(cls);
        obs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.16, rootMargin: '0px 0px -8% 0px' });

  document.querySelectorAll(selector).forEach((el) => obs.observe(el));
}

function initNavState() {
  const nav = document.querySelector('.nav');
  if (!nav) return;
  const update = () => nav.classList.toggle('is-scrolled', window.scrollY > 24);
  update();
  window.addEventListener('scroll', update, { passive: true });
}

function initSpotlightCards() {
  const cards = document.querySelectorAll('.card');
  cards.forEach((card) => {
    card.addEventListener('pointermove', (event) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
      card.style.setProperty('--my', `${event.clientY - rect.top}px`);
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initScrollReveal();
  initNavState();
  initSpotlightCards();
});
```

### Entrance Animation
```css
.reveal {
  opacity: 0;
  transform: translateY(28px);
  transition: opacity 700ms cubic-bezier(0.16, 1, 0.3, 1),
              transform 700ms cubic-bezier(0.16, 1, 0.3, 1);
}

.reveal.in-view {
  opacity: 1;
  transform: translateY(0);
}

.reveal.in-view > *:nth-child(1) { transition-delay: 0ms; }
.reveal.in-view > *:nth-child(2) { transition-delay: 90ms; }
.reveal.in-view > *:nth-child(3) { transition-delay: 180ms; }
.reveal.in-view > *:nth-child(4) { transition-delay: 270ms; }

@keyframes gradientText {
  0% { background-position: 0% 50%; }
  100% { background-position: 100% 50%; }
}

.gradient-text {
  color: transparent;
  background: linear-gradient(90deg, var(--text), var(--accent), var(--accent-strong), var(--text));
  background-size: 220% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  animation: gradientText 7s ease-in-out infinite alternate;
}
```

### Scroll Behavior
```css
html { scroll-behavior: smooth; }
[id] { scroll-margin-top: 88px; }

.parallax-soft {
  transform: translateY(var(--parallax-y, 0));
  transition: transform 120ms linear;
}
```

### Hover & Focus States
- 所有按钮、导航链接、截图卡片、证据卡片必须有 hover 状态。
- 所有链接和按钮必须有 `:focus-visible`。
- 对话截图卡片 hover 只轻微上浮，不旋转，避免影响可读性。

### Required L2 Signature Moments
1. Hero H1 渐变文字入场。
2. Scenario cards 滚动 reveal + stagger。
3. Conversation mockup hover spotlight。
4. Evidence panel 的支撑状态 badge 轻微 glow。
5. Section H2 reveal。
6. 背景使用低成本 radial-gradient 氛围层。

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  .reveal {
    opacity: 1 !important;
    transform: none !important;
  }
}
```

## 8. Do's and Don'ts

**Do:**
1. 先讲用户场景，再解释背后的 Agent / RAG / KG 能力。
2. 每个示例截图必须包含“用户问题 + 系统回答 + 证据/状态”。
3. 对 Research Workflow 用“研究助理正在做什么”解释，不直接堆节点名。
4. 对证据状态使用清晰中文：已支撑、部分支撑、证据不足、待补证。
5. 保持深色背景和高对比文字，保证 GitHub 访问者快速阅读。
6. 用 Bento 和对话卡片代替大段流程图。
7. 让每个 CTA 明确去向：开始使用、阅读功能介绍、查看架构。
8. 移动端优先保证截图可横向压缩和正文可读。

**Don't:**
1. 不要在第一屏放复杂系统架构图。
2. 不要直接写“卖点一、卖点二”，要写用户能完成的事情。
3. 不要把所有技术名词一次性堆给访客。
4. 不要使用大面积霓虹、故障风或高频动效。
5. 不要用纯色块占位截图；必须使用 mock conversation 或真实 UI 截图。
6. 不要让证据面板只显示 URL，必须有标题、来源、摘要和支撑状态。
7. 不要把“supported=true”直接翻译为完全正确；有 unsupported claims 时展示为部分支撑。
8. 不要在移动端保留三列卡片或过宽代码块。
9. 不要默认使用 emoji 作为视觉系统，图标使用内联 SVG 或现有图标库。
10. 不要为了动效牺牲滚动流畅度。

## 9. Responsive Behavior

**Breakpoints:**
```css
:root {
  --bp-mobile: 600px;
  --bp-tablet: 860px;
  --bp-desktop: 1180px;
}
```

**Desktop ≥ 1180px:**
- Hero 使用双栏：左侧叙事文案，右侧产品 mockup。
- Conversation Demos 使用 2 列或 Bento 混排。
- Evidence panel 可以和答案卡片并排展示。

**Tablet 600px-1179px:**
- Hero 改为上下结构，mockup 宽度 100%。
- Bento 卡片变为 2 列或主次混排。
- 导航保留主要锚点，次要链接折叠。

**Mobile ≤ 600px:**
- 所有 grid 单列。
- Hero H1 不超过 44px。
- 对话 mockup 保持 100% 宽，消息气泡最大宽度 92%。
- 证据卡片摘要默认显示 3-4 行。
- 触摸目标不小于 44px。
- 禁止横向溢出；代码块和 URL 使用 `overflow-wrap: anywhere`。

**Mobile CSS:**
```css
@media (max-width: 600px) {
  .container { width: min(100% - 32px, 1180px); }
  .section { padding-block: 56px; }
  .hero { padding-block: 64px 48px; }
  .hero h1 { font-size: clamp(38px, 11vw, 48px); }
  .nav-links { display: none; }
  .message { max-width: 92%; }
  .card { border-radius: 20px; }
}
```

## Screenshot & Demo Asset Plan

生成页面或展示资源时，需要制作 5 张对话/产品示例图。所有截图都采用同一套深色研究工作台视觉，尺寸优先使用 `1200x720` SVG，便于 GitHub README 展示。

1. **Paper Assistant 论文阅读**
   - 用户问题：`请概括这篇论文的研究问题、核心方法、实验设计和主要贡献。`
   - 展示内容：论文助手模式、本地论文片段来源、方法/实验/贡献结构化回答。

2. **Research 研究空白分析**
   - 用户问题：`Agentic RAG 在 2026 年还有哪些最新研究空白？请基于证据给出一个可做的研究问题。`
   - 展示内容：研究意图识别、本地证据不足、联网补证、生成研究问题。

3. **Evidence Transparency 原始证据面板**
   - 展示内容：两条论文证据、标题、作者、年份、Semantic Scholar URL、支撑状态。
   - 必须出现“部分支撑”语义，体现严谨性。

4. **Self-RAG 可靠性验证**
   - 用户问题：`这个结论可靠吗？请基于论文和官网依据验证。`
   - 展示内容：证据评分、检索修复、联网验证、最终支持程度。

5. **Knowledge Graph 知识图谱探索**
   - 用户问题：`搜索 Self-RAG 相关概念，并查看它和 RAG、反思机制、事实性评估之间的关系。`
   - 展示内容：节点、关系、局部图谱、关联论文或概念。
