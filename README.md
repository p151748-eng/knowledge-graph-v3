# KG-Agent System v2

> 知识图谱增强的 RAG 问答系统，支持多 Agent 协作、流式输出与可视化图谱。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React)                     │
│  ChatPage · KGPage · DocsPage · IngestPage · Settings   │
└───────────────────────┬─────────────────────────────────┘
                        │ REST + SSE
┌───────────────────────▼─────────────────────────────────┐
│                    Backend (FastAPI)                     │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ Chat API │  │ 3-Agent Pipe  │  │  KG Search API  │  │
│  └──────────┘  │ KGRetriever  │  └─────────────────┘  │
│                │ Explainer     │                        │
│                │ Integrator    │                        │
│                └──────────────┘                         │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ Hybrid Search│  │  Doc Ingest  │  │ Web Search  │  │
│  └──────────────┘  └──────────────┘  └─────────────┘  │
└───────┬──────────────────┬─────────────────────────────┘
        │                  │
   ┌────▼────┐       ┌─────▼─────┐
   │  MySQL  │       │  Chroma   │
   │(关系/文档)│       │(向量检索)  │
   └─────────┘       └───────────┘
```

## 核心功能

| 功能 | 说明 |
|------|------|
| **智能路由** | 自动判断问题复杂度，选择快速路径或完整 Agent 流水线 |
| **3-Agent 流水线** | KGRetriever（检索）→ Explainer（解释）→ Integrator（生成） |
| **混合检索** | 关键词 + 语义向量 + 知识图谱扩展，三路召回融合 |
| **联网搜索** | DuckDuckGo 实时搜索，结果自动沉淀到知识图谱 |
| **流式输出** | SSE 实时推送，逐字渲染，支持 Markdown 格式化 |
| **知识图谱可视化** | ForceGraph2D 交互式图谱，支持节点/边的增删改 |
| **多 LLM 支持** | 通义千问、OpenAI GPT、Claude、DeepSeek |

## 快速启动

### 前置要求

- Python 3.10+
- Node.js 18+
- MySQL 8.0+（或使用 Docker）

### 1. 克隆并安装依赖

```bash
# 后端
cd backend
pip install -r ../requirements.txt

# 前端
cd frontend
npm install
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```bash
# 数据库
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/knowledge_graph

# LLM - 至少配置一项
QWEN_API_KEY=sk-xxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
DEEPSEEK_API_KEY=sk-xxxxxxxx

# LLM 默认配置
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
LLM_TEMPERATURE=0.7
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
cp .env.example .env  # 填入 API Key
docker-compose up
```

## 项目结构

```
kg v3/
├── backend/
│   ├── main.py              # FastAPI 主入口，路由定义
│   ├── config.py           # 配置管理
│   ├── models/
│   │   ├── api.py          # Pydantic API Schema
│   │   └── db.py           # SQLAlchemy ORM 模型
│   ├── services/
│   │   ├── chat.py         # 对话服务
│   │   ├── kg.py           # 知识图谱服务
│   │   ├── ingest.py       # 文档摄取服务
│   │   └── retrieval.py     # 检索服务
│   ├── agents/
│   │   ├── pipeline.py      # 3-Agent 流水线编排
│   │   ├── kg_retriever.py  # 知识检索 Agent
│   │   ├── explainer.py     # 通俗解释 Agent
│   │   └── integrator.py    # 答案整合 Agent
│   ├── tools/
│   │   ├── hybrid_search.py # 混合检索工具
│   │   ├── kg_extract.py    # 实体/关系抽取工具
│   │   ├── web_search.py    # 联网搜索工具
│   │   └── doc_store.py     # 文档存储工具
│   ├── llm/
│   │   ├── manager.py       # LLM 管理器（多提供商）
│   │   └── client.py        # LLM HTTP 客户端
│   └── chroma/manager.py    # Chroma 向量数据库
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx    # 对话页面（SSE 流式）
│   │   │   ├── KGPage.tsx      # 知识图谱可视化
│   │   │   ├── DocsPage.tsx    # 文档管理
│   │   │   ├── IngestPage.tsx  # 文档导入
│   │   │   └── SettingsPage.tsx # LLM 配置
│   │   ├── api/client.ts       # API 客户端
│   │   ├── store/useStore.ts   # Zustand 状态管理
│   │   └── types/index.ts       # TypeScript 类型
│   └── package.json
├── mysql/init.sql           # 数据库初始化脚本
├── docker-compose.yml       # Docker 部署配置
├── requirements.txt         # Python 依赖
└── README.md
```

## API 文档

启动后访问 `http://localhost:8003/docs`（Swagger UI）

### 核心接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat/stream` | SSE 流式对话 |
| `POST` | `/api/websearch` | 联网搜索 |
| `GET` | `/api/kg/graph` | 图谱可视化数据 |
| `GET` | `/api/kg/nodes` | 节点列表 |
| `POST` | `/api/kg/nodes` | 创建节点 |
| `GET` | `/api/kg/edges` | 关系列表 |
| `POST` | `/api/kg/edges` | 创建关系 |
| `DELETE` | `/api/kg/edges/{id}` | 删除关系 |
| `POST` | `/api/ingest` | 摄取文档 |
| `GET` | `/api/convs` | 历史对话 |
| `GET` | `/api/settings` | 获取 LLM 配置 |
| `PUT` | `/api/settings` | 更新 LLM 配置 |

## 3-Agent 流水线

```
用户问题
    │
    ▼
┌───────────────────┐
│   KGRetriever     │  检索知识图谱和文档库
│  (知识检索 Agent)  │  关键词+向量+图扩展
└────────┬──────────┘
         │ entities, relations, context
         ▼
┌───────────────────┐
│    Explainer      │  生成通俗解释和术语表
│  (通俗解释 Agent)  │  复杂概念→易懂语言
└────────┬──────────┘
         │ explanations, glossary
         ▼
┌───────────────────┐
│    Integrator     │  综合生成最终回答
│  (答案整合 Agent)  │  引用来源，附带置信度
└───────────────────┘
         │
         ▼
    最终回答 + 来源 + 置信度
```

## 配置说明

### LLM 提供商

系统支持同时配置多个 LLM 提供商，通过 `Settings` 页面实时切换：

| 提供商 | 环境变量 | 模型 |
|--------|----------|------|
| 通义千问 | `QWEN_API_KEY` | qwen-plus, qwen-turbo, qwen-max |
| OpenAI | `OPENAI_API_KEY` | gpt-4o, gpt-4-turbo, gpt-3.5-turbo |
| Anthropic | `ANTHROPIC_API_KEY` | claude-3-5-sonnet, claude-3-opus |
| DeepSeek | `DEEPSEEK_API_KEY` | deepseek-chat, deepseek-coder |

### 问题路由策略

- **Fast Path**（简单问题）：单次检索 + LLM 生成，~2秒响应
- **Pipeline**（复杂问题）：3-Agent 完整流水线，~5-8秒响应

前端可手动切换路径模式（Auto/Fast/Pipeline）。

## 开发指南

### 添加新的 LLM 提供商

1. 在 `llm/client.py` 添加 `_call_xxx` 方法
2. 在 `llm/manager.py` 的 `valid_providers` 注册
3. 前端 `SettingsPage.tsx` 的 `PROVIDER_MODELS` 添加模型列表

### 添加新的工具

1. 继承 `tools/base.py` 的 `BaseTool`
2. 在 `tools/registry.py` 注册
3. 在 Agent 中通过 `ToolRegistry` 调用

## License

MIT
