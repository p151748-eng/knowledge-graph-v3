# KG-Agent 技术参考

> 这里保留 README 中不适合放在首页的技术细节：系统架构、页面功能、快速开始、API、文档索引、技术栈和项目状态。

## 系统架构

<p align="center">
  <img src="assets/architecture.svg" alt="KG-Agent Architecture" width="100%" />
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

更多架构细节见 [ARCHITECTURE.md](../ARCHITECTURE.md)。

## 主要工作流

### Paper Assistant

<p align="center">
  <img src="assets/workflow-paper-assistant.svg" alt="Paper Assistant Workflow" width="100%" />
</p>

适合论文阅读、选题分析、研究空白、相关工作和引用补充。典型两轮对话：

```text
我想研究“多智能体 RAG 在医学论文阅读中的应用”，帮我分析这个选题的研究空白和创新点。

帮我联网搜索这个选题的相关论文，重点找 2024 年以后的最新研究。
```

系统会识别第二轮是上下文追问，继承上一轮选题，将搜索 query 压缩为学术检索友好的表达，优先召回真实论文，并在回答中输出 `[1]`、`[2]` 等引用标记和引用链接。

### Self-RAG / CRAG

<p align="center">
  <img src="assets/workflow-self-rag.svg" alt="Self-RAG Workflow" width="100%" />
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

如果使用仓库脚本，注意 [run.sh](../run.sh) 和 [run.bat](../run.bat) 当前默认使用后端端口 `8003`。

## 操作演示

完整可复制演示见 [demo.md](demo.md)，包括：

- 论文选题研究空白分析 + 2024 年后最新论文联网补充。
- arXiv 论文导入 + Paper Assistant 问答。
- Self-RAG 可靠性验证。
- 知识图谱检索与可视化。

## 操作手册

使用者手册见 [user-guide.md](user-guide.md)，覆盖：

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

完整接口说明见 [API.md](../API.md)。

## 文档索引

- [ARCHITECTURE.md](../ARCHITECTURE.md)：系统架构和核心模块。
- [API.md](../API.md)：REST API 说明。
- [DEVELOPMENT.md](../DEVELOPMENT.md)：开发环境和项目结构。
- [DEPLOYMENT.md](../DEPLOYMENT.md)：部署与运维。
- [REQUIREMENTS.md](../REQUIREMENTS.md)：需求说明。
- [product-showcase.html](product-showcase.html)：面向 GitHub 访客的产品展示页和对话示例截图。
- [feature-manual.md](feature-manual.md)：面向使用者的功能介绍、真实场景和示例问题。
- [user-guide.md](user-guide.md)：用户操作手册。
- [demo.md](demo.md)：演示脚本。

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
