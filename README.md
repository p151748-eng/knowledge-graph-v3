# KG-Agent System v3

<p align="center">
  <img src="docs/assets/hero.svg" alt="KG-Agent System v3" width="100%" />
</p>

<p align="center">
  <strong>面向论文阅读、研究选题与知识沉淀的知识图谱增强 RAG 系统</strong>
</p>

<p align="center">
  <a href="docs/product-showcase.html">产品展示</a> ·
  <a href="docs/feature-manual.md">功能介绍</a> ·
  <a href="ARCHITECTURE.md">Architecture</a> ·
  <a href="API.md">API</a> ·
  <a href="docs/user-guide.md">User Guide</a> ·
  <a href="docs/demo.md">Demo</a> ·
  <a href="DEVELOPMENT.md">Development</a> ·
  <a href="DEPLOYMENT.md">Deployment</a>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.109%2B-009688" />
  <img alt="React" src="https://img.shields.io/badge/React-18-61DAFB" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5-3178C6" />
  <img alt="RAG" src="https://img.shields.io/badge/RAG-KG%20Enhanced-6B8AED" />
</p>

KG-Agent System v3 是一个面向个人学习、论文阅读、研究选题分析和知识管理的智能知识库系统。它把 RAG、知识图谱、多 Agent 工作流、上下文记忆、证据校验、联网搜索和学术论文检索组合在一起，让用户可以在同一个界面完成文档导入、知识沉淀、论文问答、研究空白分析、最新论文补充和可视化图谱探索。

> 想先像浏览产品官网一样快速了解项目，请看 [产品展示页](docs/product-showcase.html)；想按场景阅读完整介绍，请看 [功能介绍](docs/feature-manual.md)。

## 为什么需要 KG-Agent

普通 RAG 系统通常能回答“文档里有什么”，但在论文阅读和研究规划场景中还需要更多能力：

- 需要区分简单问答、复杂分析、论文阅读、研究规划、事实验证等不同任务。
- 需要在本地知识库证据不足时主动提示并补充联网证据。
- 需要优先搜索真实论文，并在回答中保留规范引用标记和来源链接。
- 需要把文档、论文、概念、方法、实验和关系沉淀成可检索的知识图谱。
- 需要在长对话中记住当前选题、研究方向和上下文追问。

KG-Agent 面向这些问题设计了多路径工作流和证据驱动回答机制。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 动态多工作流路由 | 根据问题意图自动选择 FastPath、KG Pipeline、Paper Assistant、Self-RAG 或 Research Workflow。 |
| Paper Assistant | 面向论文概览、方法解释、实验分析、相关工作、研究空白和写作大纲等任务。 |
| 学术联网检索 | 论文类“联网补充”优先走 AI4Scholar 学术检索，并保留作者、年份、paper_id、URL 和引用标记。 |
| Self-RAG / CRAG | 对证据不足或需要验证的问题进行检索评分、检索修复、联网验证和答案校验。 |
| Knowledge Graph | 支持节点/边管理、图谱搜索、ForceGraph2D 可视化和论文结构化图谱。 |
| 文档与论文导入 | 支持文本、文件和 arXiv 论文导入，自动分片、向量化和实体关系抽取。 |
| 上下文记忆 | 结合近期对话、长期摘要、任务状态和向量召回，识别“这个选题”“继续刚才”等追问。 |
| 可观测回答 | 前端展示路径、来源、执行步骤、证据评分、检索轮次和性能指标。 |


## 产品展示

如果你想先用 1 分钟了解 KG-Agent 能解决什么问题，可以打开 [docs/product-showcase.html](docs/product-showcase.html)，里面包含面向 GitHub 展示的产品页和 5 个对话示例截图。

## 功能展示

### 研究助手：从模糊问题到可做研究选题

<p align="center">
  <img src="docs/assets/demo-research-assistant.svg" alt="Research Assistant Demo" width="100%" />
</p>

### 证据透明：看到每条证据从哪里来

<p align="center">
  <img src="docs/assets/demo-evidence-panel.svg" alt="Evidence Panel Demo" width="100%" />
</p>

### 真实问题截图：不同问题自动进入不同工作流

下面这些截图来自本地前后端真实运行，不是重新绘制的概念图，用来展示路由选择、联网补证、论文助手和研究助手的实际界面效果。

| 问题类型 | 真实问题 | 截图 |
| --- | --- | --- |
| 简单定义 | `RAG 是什么？请用三句话解释。` | [查看截图](docs/assets/real-screenshots/fast-definition.png) |
| 复杂分析 | `请分析 Self-RAG、CRAG 和 GraphRAG 在证据检索与纠错机制上的关系。` | [查看截图](docs/assets/real-screenshots/pipeline-analysis.png) |
| 论文问题 | `请概括这篇论文的研究问题、核心方法、实验设计和主要贡献。` | [查看截图](docs/assets/real-screenshots/paper-assistant.png) |
| 研究方案 | `帮我基于 Agentic RAG 在医学场景中的应用，设计一个可做的研究方案。` | [查看截图](docs/assets/real-screenshots/research-plan.png) |
| 最新验证 | `请联网验证最近是否有 Agentic RAG 在医学场景中的新论文。` | [查看截图](docs/assets/real-screenshots/self-rag-medical-web.png) |

<p align="center">
  <img src="docs/assets/real-screenshots/self-rag-medical-web.png" alt="Real Self-RAG medical web verification screenshot" width="100%" />
</p>

更多真实场景、使用方式和示例问题见 [docs/feature-manual.md](docs/feature-manual.md)，完整产品展示页见 [docs/product-showcase.html](docs/product-showcase.html)。

## 系统架构

<p align="center">
  <img src="docs/assets/architecture.svg" alt="KG-Agent Architecture" width="100%" />
</p>

KG-Agent 由 React 前端、FastAPI 后端、多工作流编排层、工具层、数据库和外部模型/搜索服务组成。

```text
React + Vite UI
  -> FastAPI REST / SSE
  -> ChatService + ContextAwareRouter
  -> WorkflowRunner
  -> FastQA / KG Pipeline / Paper Assistant / Self-RAG / Research Workflow
  -> HybridSearch / AcademicSearch / WebSearch / KGExtract / DocStore
  -> MySQL + Chroma + LLM Providers + Bocha + AI4Scholar
```

更多架构细节见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 主要工作流

### Paper Assistant

<p align="center">
  <img src="docs/assets/workflow-paper-assistant.svg" alt="Paper Assistant Workflow" width="100%" />
</p>

适合论文阅读、选题分析、研究空白、相关工作和引用补充。典型两轮对话：

```text
我想研究“多智能体 RAG 在医学论文阅读中的应用”，帮我分析这个选题的研究空白和创新点。

帮我联网搜索这个选题的相关论文，重点找 2024 年以后的最新研究。
```

系统会识别第二轮是上下文追问，继承上一轮选题，将搜索 query 压缩为学术检索友好的表达，优先召回真实论文，并在回答中输出 `[1]`、`[2]` 等引用标记和引用链接。

### Self-RAG / CRAG

<p align="center">
  <img src="docs/assets/workflow-self-rag.svg" alt="Self-RAG Workflow" width="100%" />
</p>

适合“是否可靠”“是否有依据”“最新情况”“帮我验证”等问题。系统先评估本地证据是否足够，再决定是否进行检索修复、联网验证或学术论文补证。

## 页面功能

| 页面 | 路径 | 功能 |
| --- | --- | --- |
| 聊天 | `/` | 流式对话、路径选择、路线预测、来源展示、执行步骤和指标展示。 |
| 知识导入 | `/import` | 手动文本、文件和 arXiv 论文导入。 |
| 文档库 | `/docs` | 文档列表、详情、分片和删除管理。 |
| 知识图谱 | `/kg` | 图谱可视化、节点/边管理、图谱搜索和论文图谱检索。 |
| 设置 | `/settings` | LLM 提供商、模型和温度参数配置。 |

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- MySQL 8.0+
- 至少一个可用 LLM API Key
- 可选：Bocha API Key、AI4Scholar 相关配置，用于联网搜索与学术检索

### 2. 安装依赖

```bash
git clone https://github.com/p151748-eng/knowledge-graph-v3.git
cd knowledge-graph-v3

pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

### 3. 配置环境变量

复制后端环境变量模板：

```bash
cp backend/.env.example backend/.env
```

至少配置数据库和一个 LLM 提供商：

```env
DATABASE_URL=mysql+pymysql://root:your-password@localhost:3306/konw
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
QWEN_API_KEY=your-qwen-key

BOCHA_SEARCH_ENABLED=true
BOCHA_API_KEY=your-bocha-api-key
```

不要提交真实 `.env` 或任何 API Key。

### 4. 启动服务

后端：

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

前端：

```bash
cd frontend
npm run dev
```

浏览器打开：

```text
http://localhost:5173
```

如果使用仓库脚本，注意 [run.sh](run.sh) 和 [run.bat](run.bat) 当前默认使用后端端口 `8003`。

## 操作演示

完整可复制演示见 [docs/demo.md](docs/demo.md)，包括：

- 论文选题研究空白分析 + 2024 年后最新论文联网补充。
- arXiv 论文导入 + Paper Assistant 问答。
- Self-RAG 可靠性验证。
- 知识图谱检索与可视化。

## 操作手册

使用者手册见 [docs/user-guide.md](docs/user-guide.md)，覆盖：

- 启动前准备。
- 页面导航。
- 论文导入与问答。
- 联网搜索和引用来源查看。
- 知识图谱使用。
- 常见问题排查。

## API 入口

| API | 说明 |
| --- | --- |
| `POST /api/chat` | 自动路由对话。 |
| `POST /api/chat/stream` | SSE 流式对话。 |
| `POST /api/chat/paper` | 强制论文助手路径。 |
| `POST /api/chat/self-rag` | 强制 Self-RAG 路径。 |
| `POST /api/websearch` | 联网搜索。 |
| `POST /api/academic-search` | 学术论文搜索。 |
| `POST /api/ingest` | 手动文档导入。 |
| `POST /api/ingest/arxiv` | arXiv 论文导入。 |
| `GET /api/kg/graph` | 图谱可视化数据。 |

完整接口说明见 [API.md](API.md)。

## 文档索引

- [ARCHITECTURE.md](ARCHITECTURE.md)：系统架构和核心模块。
- [API.md](API.md)：REST API 说明。
- [DEVELOPMENT.md](DEVELOPMENT.md)：开发环境和项目结构。
- [DEPLOYMENT.md](DEPLOYMENT.md)：部署与运维。
- [REQUIREMENTS.md](REQUIREMENTS.md)：需求说明。
- [docs/product-showcase.html](docs/product-showcase.html)：面向 GitHub 访客的产品展示页和对话示例截图。
- [docs/feature-manual.md](docs/feature-manual.md)：面向使用者的功能介绍、真实场景和示例问题。
- [docs/user-guide.md](docs/user-guide.md)：用户操作手册。
- [docs/demo.md](docs/demo.md)：演示脚本。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, React Query, React Markdown, ForceGraph2D |
| Backend | FastAPI, Uvicorn, SQLAlchemy, Pydantic, SSE |
| Retrieval | BM25, semantic search, graph expansion, Chroma vector store |
| Knowledge Graph | MySQL nodes/edges/documents, paper graph builder |
| LLM | Qwen, OpenAI-compatible providers, Anthropic, DeepSeek |
| External Evidence | Bocha Web Search, AI4Scholar academic search |

## 项目状态

当前版本聚焦个人知识库和论文研究工作流，适合本地运行、个人研究和二次开发。生产部署前建议补充认证、权限控制、密钥管理、任务队列和更完整的监控告警。
