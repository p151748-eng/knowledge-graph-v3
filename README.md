# KG-Agent System v3

> 知识图谱增强的 RAG 问答系统，支持多路径智能路由、多 Agent 工作流、四层记忆压缩、证据校验、论文助手与研究规划。

---

## 系统概述

KG-Agent System v3 是面向个人学习、知识管理与论文阅读场景的智能知识库系统。系统结合 RAG、知识图谱、多 Agent 工作流、分层记忆、证据校验与联网验证，支持文档导入、知识沉淀、混合检索、智能问答、论文分析、研究综述与技术路线规划。

系统通过上下文感知路由器对用户问题进行意图识别与轻量级任务规划，根据问题类型动态选择 FastPath、KG Pipeline、Self-RAG、Paper Assistant 或 Research Workflow 等执行路径，在响应效率、上下文连续性和答案可信度之间取得平衡。

---

## 核心机制

### 1. 上下文感知路由与多路径工作流

用户输入后，系统先构建 Memory Context，再由 `ContextAwareRouter` 输出 `RouteDecision`，最后由 `WorkflowRunner` 调度对应路径。

```
用户问题
   ↓
加载近期对话与 Memory Context
   ↓
ContextAwareRouter 意图识别、复杂度评估、上下文判断
   ↓
RouteDecision(path, intent, topic_changed, confidence)
   ↓
WorkflowRunner 调度对应 Workflow
   ↓
返回答案、证据来源、置信度、校验结果、执行轨迹
```

路由判断规则：

| 判断条件 | 路由结果 | 说明 |
|---|---|---|
| 用户显式指定 `force_path` | 指定路径 | 直接使用用户指定的 `fast`、`pipeline`、`self_rag`、`paper_assistant` 或 `research` |
| 当前问题是上下文追问 | 继承上一轮路径 | 如 "继续"、"这个呢"、"为什么"，复用上一轮 path |
| 包含论文关键词 | `paper_assistant` | 单篇论文理解、方法解释、实验分析、论文对比 |
| 包含验证/时效性关键词 | `self_rag` | 需要证据验证、可靠性判断、时效性查证 |
| 包含研究规划/方案设计关键词 | `research` | 研究综述、技术路线、方案设计、研究空白分析 |
| 包含复杂分析/对比关键词 | `pipeline` | 普通知识库中的复杂分析或关系型问题 |
| 问题较短或定义类问题 | `fast` | 简单事实问答、通用知识问答、闲聊 |

各路径对应节点：

| 路径 | 中文名称 | 主要阶段 | 适用问题 |
|---|---|---|---|
| `fast` | 快速问答路径 | 混合检索 → 直接生成 → 轻量引用校验 | 简单事实问答、闲聊 |
| `pipeline` | KG 多 Agent 分析路径 | KG 检索 → 术语解释 → 答案整合 | 复杂知识分析、概念关系、对比归纳 |
| `self_rag` | 自校验 RAG 路径 | 本地检索 → 证据评估 → 检索修正 → 联网验证 → 答案生成 → 答案校验 | 证据验证、时效性问题、可靠性判断 |
| `paper_assistant` | 论文助手路径 | 论文任务规划 → 论文证据检索 → 证据评估 → 专家生成 → 引用校验 | 单篇论文概览、方法解释、实验分析、论文对比 |
| `research` | 研究规划工作流路径 | 问题解析与规划 → 多源证据召回 → 证据驱动生成 → 主张级证据校验 → 结果聚合 | 研究综述、方案设计、技术路线、研究空白分析 |

---

### 2. 四层记忆压缩与意图聚焦

系统融合近期对话、长期摘要、结构化任务状态和向量化记忆召回，构建 Memory Context；通过 `active_focus` 跟踪当前关注主题，识别"继续刚才"、"换一个"、"回到前面"、"对比一下"等语义信号，缓解长对话中的上下文遗忘、指代混乱和语义漂移。

记忆服务 `MemoryService` 提供：

- `load_recent_turns`: 加载最近 N 轮对话
- `build_memory_context`: 构建摘要 + 任务状态 + 记忆片段 + prompt
- `recall`: 向量 + SQL 双路召回相关记忆
- `update_active_focus`: 根据"切换/回退/比较"信号更新焦点
- `compress_if_needed`: 达到阈值后 LLM 增量压缩对话为长期摘要

---

### 3. 分层证据校验机制

系统在生成前通过 `EvidenceGraderAgent` 判断检索证据是否足以回答问题，决定是否查询改写、调整检索策略、联网验证或拒答；生成后通过 `AnswerVerifierAgent` 和 `CitationVerifierAgent` 校验答案是否被证据支撑，并输出主张级证据覆盖情况。

Self-RAG 路径额外引入 `WebSearchVerifierAgent`，在本地证据不足时联网查证并沉淀为知识图谱节点。

---

### 4. 论文助手任务规划

`PaperAssistantAgent` 通过 `PaperTaskRouter` 识别论文概览、方法解释、实验分析、方法对比、文献综述和写作大纲等任务类型，并为不同任务生成 chunk 偏好、检索策略和回答结构，实现面向论文阅读场景的结构化问答。

---

## 已实现功能清单

### 后端核心模块

| 模块 | 文件 | 功能 |
|---|---|---|
| 路由器 | `backend/core/router.py` | 上下文感知路由、意图识别、复杂度评分、追问继承 |
| 工作流编排 | `backend/core/orchestrator.py` | WorkflowRegistry、WorkflowRunner、BaseWorkflow 抽象 |
| Agent 上下文 | `backend/core/context.py` | AgentContext、PipelineData、各阶段数据结构 |
| 状态与证据 | `backend/core/graph_state.py` | WorkflowState、EvidenceItem、引用校验数据 |
| 快速问答工作流 | `backend/agents/workflows.py::FastQAWorkflow` | 混合检索 → 直接生成 → CitationVerifier |
| KG Pipeline 工作流 | `backend/agents/workflows.py::KGPipelineWorkflow` | AgentPipeline 三阶段编排 |
| Self-RAG 工作流 | `backend/agents/workflows.py::SelfRAGWorkflow` | 本地检索、证据评估、检索修正、联网验证、答案校验 |
| 论文助手工作流 | `backend/agents/workflows.py::PaperAssistantWorkflow` | PaperAssistantAgent 任务规划与生成 |
| 研究规划工作流 | `backend/agents/planned_workflow.py::ResearchWorkflow` | 多源召回、证据驱动生成、主张级校验 |
| 记忆服务 | `backend/services/memory.py` | 四层记忆、焦点跟踪、增量压缩、向量召回 |
| 混合检索 | `backend/tools/hybrid_search.py` | BM25 + 语义向量 + 图扩展、三路融合 |
| 联网搜索 | `backend/tools/web_search.py` | DuckDuckGo 搜索、结果沉淀到 KG/文档库 |
| 知识图谱抽取 | `backend/tools/kg_extract.py` | LLM 实体/关系抽取 |
| 文档导入 | `backend/services/ingest.py` | 文本/PDF 导入、分片、向量化、KG 构建 |
| 论文图谱构建 | `backend/services/paper_graph_builder.py` | 论文结构化图谱：方法、实验、指标、引用关系 |
| LLM 管理器 | `backend/llm/manager.py` | 多提供商统一接口、嵌入向量、流式调用 |
| Chroma 向量库 | `backend/chroma/manager.py` | 向量持久化、相似度检索、内存集合支持 |

### 前端页面

| 页面 | 路径 | 功能 |
|---|---|---|
| 对话页 | `/` (ChatPage) | SSE 流式对话、路径选择、Markdown 渲染、来源展示 |
| 文档导入 | `/import` (IngestPage) | 文本/PDF/Arxiv 导入、进度显示 |
| 文档管理 | `/docs` (DocsPage) | 文档列表、详情、删除、图谱关联 |
| 知识图谱 | `/kg` (KGPage) | ForceGraph2D 可视化、节点/边增删改、搜索 |
| 系统设置 | `/settings` (SettingsPage) | LLM 提供商切换、模型选择、参数调整 |

### API 端点

| 分类 | 端点 | 功能 |
|---|---|---|
| 对话 | `POST /api/chat` | 智能路由对话 |
| 对话 | `POST /api/chat/stream` | SSE 流式对话 |
| 对话 | `POST /api/chat/fast` | 强制 FastPath |
| 对话 | `POST /api/chat/pipeline` | 强制 KG Pipeline |
| 对话 | `POST /api/chat/paper` | 强制论文助手 |
| 对话 | `POST /api/chat/self-rag` | 强制 Self-RAG |
| 联网搜索 | `POST /api/websearch` | DuckDuckGo 搜索并沉淀 |
| 文档导入 | `POST /api/ingest` | 文本导入 |
| 文档导入 | `POST /api/ingest/file` | 文件上传导入 |
| 文档导入 | `POST /api/ingest/arxiv` | Arxiv 论文导入 |
| 文档管理 | `GET /api/docs` | 文档列表 |
| 文档管理 | `GET /api/docs/{id}` | 文档详情 |
| 文档管理 | `GET /api/docs/{id}/chunks` | 文档分片列表 |
| 文档管理 | `DELETE /api/docs/{id}` | 删除文档 |
| 知识图谱 | `GET /api/kg/nodes` | 节点列表 |
| 知识图谱 | `POST /api/kg/nodes` | 创建节点 |
| 知识图谱 | `PUT /api/kg/nodes/{id}` | 更新节点 |
| 知识图谱 | `DELETE /api/kg/nodes/{id}` | 删除节点 |
| 知识图谱 | `GET /api/kg/edges` | 关系列表 |
| 知识图谱 | `POST /api/kg/edges` | 创建关系 |
| 知识图谱 | `DELETE /api/kg/edges/{id}` | 删除关系 |
| 知识图谱 | `GET /api/kg/search` | 图谱搜索 |
| 知识图谱 | `GET /api/kg/graph` | 全图可视化数据 |
| 对话历史 | `GET /api/convs` | 对话列表 |
| 对话历史 | `GET /api/convs/{id}` | 对话详情 |
| 对话历史 | `DELETE /api/convs/{id}` | 删除对话 |
| 系统设置 | `GET /api/settings` | 获取 LLM 配置 |
| 系统设置 | `PUT /api/settings` | 更新 LLM 配置 |
| 健康 | `GET /api/health` | 服务状态检查 |

---

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Frontend (React + Vite)                         │
│   ChatPage · IngestPage · DocsPage · KGPage · SettingsPage           │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ REST API + SSE
┌───────────────────────────────▼─────────────────────────────────────┐
│                        Backend (FastAPI)                              │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                     ChatService                                 │ │
│  │  _route → ContextAwareRouter → RouteDecision                    │ │
│  │  _build_context → AgentContext + MemoryContext                  │ │
│  │  workflow_runner.run → WorkflowResult                           │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                 │                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                   WorkflowRegistry                              │ │
│  │  fast → FastQAWorkflow                                          │ │
│  │  pipeline → KGPipelineWorkflow                                  │ │
│  │  self_rag → SelfRAGWorkflow                                     │ │
│  │  paper_assistant → PaperAssistantWorkflow                       │ │
│  │  research → ResearchWorkflow                                    │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                 │                                     │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐            │
│  │ Agents        │  │ Tools         │  │ Services      │            │
│  │               │  │               │  │               │            │
│  │ KGRetriever   │  │ HybridSearch  │  │ MemoryService │            │
│  │ Explainer     │  │ WebSearch     │  │ IngestService │            │
│  │ Integrator    │  │ KGExtract     │  │ KGService     │            │
│  │ EvidenceGrader│  │ DocStore      │  │ RetrievalSvc  │            │
│  │ RetrievalRepair│ │ BM25Search    │  │ GraphRetrieval│            │
│  │ WebVerifier   │  │               │  │               │            │
│  │ AnswerVerifier│  │               │  │               │            │
│  │ CitationVerify│  │               │  │               │            │
│  │ PaperAssistant│  │               │  │               │            │
│  │ ResearchWF    │  │               │  │               │            │
│  └───────────────┘  └───────────────┘  └───────────────┘            │
│                                 │                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                     LLM Manager                                 │ │
│  │  Qwen / OpenAI / Anthropic / DeepSeek                           │ │
│  │  complete / complete_json / embed / stream                      │ │
│  └────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │
           ┌─────────────────────┴─────────────────────┐
           ▼                                           ▼
┌─────────────────────┐                     ┌─────────────────────┐
│   MySQL (关系型)     │                     │   Chroma (向量库)   │
│                     │                     │                     │
│  nodes              │                     │  doc_chunks         │
│  edges              │                     │  conversation_memory│
│  documents          │                     │                     │
│  document_chunks    │                     │                     │
│  conversations      │                     │                     │
│  conversation_summary│                     │                     │
│  conversation_memory_items│                     │                     │
└─────────────────────┘                     └─────────────────────┘
```

---

## 快速启动

### 前置要求

- Python 3.10+
- Node.js 18+
- MySQL 8.0+（或使用 Docker）

### 1. 克隆并安装依赖

```bash
git clone https://github.com/p151748-eng/knowledge-graph-v3.git
cd knowledge-graph-v3

# 后端
pip install -r requirements.txt

# 前端
cd frontend
npm install
cd ..
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件（参考 `backend/.env.example`）：

```bash
# 数据库
DATABASE_URL=mysql+pymysql://root:your-password@localhost:3306/konw

# LLM - 至少配置一项（填写真实 Key，不要提交到 Git）
QWEN_API_KEY=your-qwen-key
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
DEEPSEEK_API_KEY=your-deepseek-key

# LLM 默认配置
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
LLM_TEMPERATURE=0.7

# Chroma 向量库
CHROMA_PERSIST_DIR=./chroma_data

# Self-RAG 配置
CRAG_ALLOW_WEB=true
CRAG_WEB_MAX_RESULTS=5

# LangSmith Tracing（可选）
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=your-langsmith-key
```

### 3. 初始化数据库

```bash
# 使用 Docker（推荐）
docker-compose up db -d

# 或手动执行 mysql/init.sql
mysql -u root -p < mysql/init.sql
```

### 4. 启动服务

```bash
# 终端 1 - 后端
cd backend
python -m uvicorn main:app --reload --port 8003

# 终端 2 - 前端
cd frontend
npm run dev
```

访问 `http://localhost:5173`

### Docker 启动（完整环境）

```bash
cp backend/.env.example .env  # 填入真实 API Key（不要提交）
docker-compose up
```

---

## 项目结构

```
knowledge-graph-v3/
├── backend/
│   ├── main.py                     # FastAPI 主入口、路由定义
│   ├── config.py                   # 配置管理（从环境变量读取）
│   ├── models/
│   │   ├── api.py                  # Pydantic API Schema
│   │   ├── db.py                   # SQLAlchemy ORM 模型
│   │   └ schemas.py                # Pipeline 数据结构
│   ├── core/
│   │   ├── router.py               # ContextAwareRouter 路由器
│   │   ├── orchestrator.py         # WorkflowRegistry / WorkflowRunner
│   │   ├── context.py              # AgentContext / PipelineData
│   │   ├── graph_state.py          # WorkflowState / EvidenceItem
│   │   ├── agent.py                # Agent 抽象类与 AgentResult
│   │   └ state_graph.py            # 状态图工具类
│   ├── agents/
│   │   ├── workflows.py            # FastQA / KGPipeline / SelfRAG / PaperAssistant 工作流
│   │   ├── planned_workflow.py     # ResearchWorkflow 研究规划工作流
│   │   ├── pipeline.py             # AgentPipeline 三阶段编排
│   │   ├── kg_retriever.py         # KG 检索 Agent
│   │   ├── explainer.py            # 通俗解释 Agent
│   │   ├── integrator.py           # 答案整合 Agent
│   │   ├── evidence_grader.py      # 证据评估 Agent
│   │   ├── retrieval_repair.py     # 检索修正 Agent
│   │   ├── web_verifier.py         # 联网验证 Agent
│   │   ├── answer_verifier.py      # 答案校验 Agent
│   │   ├── citation_verifier.py    # 引用校验 Agent
│   │   ├── paper_assistant.py      # 论文助手 Agent
│   │   ├── paper_task_router.py    # 论文任务类型路由
│   │   ├── paper_experts.py        # 论文专家生成器
│   │   └ self_rag_pipeline.py      # Self-RAG 编排器
│   ├── services/
│   │   ├── chat.py                 # ChatService 对话编排入口
│   │   ├── memory.py               # MemoryService 四层记忆
│   │   ├── kg.py                   # KGService 图谱管理
│   │   ├── ingest.py               # IngestService 文档导入
│   │   ├── retrieval.py            # RetrievalService 检索封装
│   │   ├── graph_retrieval.py      # GraphRetrievalService 图谱检索
│   │   ├── paper_graph_builder.py  # 论文结构化图谱构建
│   │   ├── query_router.py         # 查询路由策略
│   │   ├── query_templates.py      # 查询模板
│   │   ├── arxiv_importer.py       # Arxiv 论文导入
│   │   └ document_processor/       # 文档解析与分块
│   ├── tools/
│   │   ├── hybrid_search.py        # 混合检索工具
│   │   ├── bm25_search.py          # BM25 关键词检索
│   │   ├── web_search.py           # 联网搜索工具
│   │   ├── kg_extract.py           # 实体/关系抽取
│   │   ├── doc_store.py            # 文档存储工具
│   │   ├── registry.py             # 工具注册表
│   │   ├── base.py                 # 工具基类
│   ├── llm/
│   │   ├── manager.py              # LLM 管理器（多提供商）
│   │   ├── client.py               # LLM HTTP 客户端
│   ├── chroma/
│   │   ├── manager.py              # Chroma 向量库管理
│   ├── observability/
│   │   ├── langsmith_tracing.py    # LangSmith 集成
│   ├── tests/                      # 测试用例目录
│   ├── .env.example                # 环境变量模板（不包含真实密钥）
│   ├── requirements.txt            # Python 依赖
│   ├── Dockerfile                  # 后端 Docker 构建文件
│   └ run.bat / run.sh              # 启动脚本
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx        # 对话页面（SSE 流式）
│   │   │   ├── IngestPage.tsx      # 文档导入页面
│   │   │   ├── DocsPage.tsx        # 文档管理页面
│   │   │   ├── KGPage.tsx          # 知识图谱可视化页面
│   │   │   ├── SettingsPage.tsx    # 系统设置页面
│   │   ├── api/
│   │   │   ├── client.ts           # API 客户端
│   │   ├── store/
│   │   │   ├── useStore.ts         # Zustand 全局状态
│   │   ├── components/
│   │   │   ├── Layout.tsx          # 页面布局
│   │   ├── types/
│   │   │   ├── index.ts            # TypeScript 类型定义
│   │   ├── App.tsx                 # React 路由配置
│   │   ├── main.tsx                # React 入口
│   │   ├── index.css               # 全局样式
│   │   └ vite-env.d.ts             # Vite 类型声明
│   ├── package.json                # 前端依赖
│   ├── vite.config.ts              # Vite 配置
│   ├── tsconfig.json               # TypeScript 配置
│   ├── tailwind.config.js          # Tailwind CSS 配置
│   ├── postcss.config.js           # PostCSS 配置
│   ├── Dockerfile                  # 前端 Docker 构建文件
│   └ index.html                    # HTML 入口
├── mysql/
│   └ init.sql                      # 数据库初始化脚本
├── chroma_data/                    # Chroma 向量数据（本地，不提交）
├── docker-compose.yml              # Docker Compose 配置
├── requirements.txt                # Python 依赖汇总
├── .gitignore                      # Git 忽略规则
├── README.md                       # 项目说明
├── ARCHITECTURE.md                 # 架构设计文档
├── API.md                          # API 接口文档
├── PROJECT_INTRO.md                # 项目介绍
├── REQUIREMENTS.md                 # 需求说明
├── DEVELOPMENT.md                  # 开发指南
├── DEPLOYMENT.md                   # 部署指南
```

---

## 配置说明

### LLM 提供商

系统支持同时配置多个 LLM 提供商，通过 `Settings` 页面实时切换：

| 提供商 | 环境变量 | 模型 |
|--------|----------|------|
| 通义千问 | `QWEN_API_KEY` | qwen-plus, qwen-turbo, qwen-max |
| OpenAI | `OPENAI_API_KEY` | gpt-4o, gpt-4-turbo, gpt-3.5-turbo |
| Anthropic | `ANTHROPIC_API_KEY` | claude-3-5-sonnet, claude-3-opus |
| DeepSeek | `DEEPSEEK_API_KEY` | deepseek-chat, deepseek-coder |

### Self-RAG 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `CRAG_ALLOW_WEB` | `true` | 是否允许联网验证 |
| `CRAG_WEB_MAX_RESULTS` | `5` | 联网搜索最大结果数 |
| `CRAG_MAX_LOCAL_ROUNDS` | `2` | 本地检索重试轮数 |
| `CRAG_MIN_RELEVANCE` | `0.70` | 证据相关性阈值 |
| `CRAG_MIN_SUPPORT` | `0.70` | 答案支撑度阈值 |
| `CRAG_MIN_COVERAGE` | `0.65` | 证据覆盖度阈值 |

---

## 安全与密钥管理

- 所有密钥（`API_KEY`、`DATABASE_URL` 密码、`LANGSMITH_API_KEY`）请填写在本地 `.env` 文件中，不要提交到 Git。
- `backend/.env.example` 只提供占位符模板，不包含真实密钥。
- `backend/config.py` 的默认值已改为占位符，确保未提交仓库不含密钥。
- 若曾意外提交密钥，请在对应平台轮换 Key。

---

## API 文档

启动后访问：

- Swagger UI: `http://localhost:8003/docs`
- ReDoc: `http://localhost:8003/redoc`

详细接口说明见 [API.md](API.md)。

---

## 开发指南

### 添加新的 LLM 提供商

1. 在 `llm/client.py` 添加 `_call_xxx` 方法
2. 在 `llm/manager.py` 的 `valid_providers` 注册
3. 前端 `SettingsPage.tsx` 的 `PROVIDER_MODELS` 添加模型列表

### 添加新的工具

1. 继承 `tools/base.py` 的 `BaseTool`
2. 在 `tools/registry.py` 注册
3. 在 Agent 中通过 `ToolRegistry` 调用

### 添加新的工作流

1. 在 `agents/` 下实现 Agent 或 Workflow
2. 在 `agents/workflows.py` 注册到 `WorkflowRegistry`
3. 在 `core/router.py` 的 `_score_paths` 添加路由评分规则

---

## 测试

```bash
PYTHONPATH=backend python backend/tests/test_self_rag_crag.py
PYTHONPATH=backend python backend/tests/test_paper_assistant_agent.py
PYTHONPATH=backend python backend/tests/test_orchestration.py
```

---

## License

MIT