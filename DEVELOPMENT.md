# KG-Agent System v2 开发指南文档

## 1. 开发环境搭建

### 1.1 系统要求

| 项目 | 版本要求 |
|------|----------|
| Python | ≥ 3.10 |
| Node.js | ≥ 18 |
| MySQL | ≥ 8.0 |
| 操作系统 | Windows/Linux/MacOS |

### 1.2 后端环境

```bash
# 1. 克隆项目
git clone https://github.com/xxx/kg-workspace-v2.git
cd kg-workspace-v2/backend

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt
```

**requirements.txt 内容：**
```
fastapi>=0.100
uvicorn>=0.23
sqlalchemy>=2.0
pymysql>=1.1
python-dotenv>=1.0
pydantic>=2.0
openai>=1.0
anthropic>=0.18
duckduckgo-search>=4.0
httpx>=0.25
```

### 1.3 前端环境

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

### 1.4 数据库准备

```sql
-- 创建数据库
CREATE DATABASE kg_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建用户（可选）
CREATE USER 'kg_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON kg_agent.* TO 'kg_user'@'localhost';
FLUSH PRIVILEGES;
```

---

## 2. 项目结构详解

### 2.1 后端目录结构

```
backend/
├── main.py              # FastAPI 入口，定义所有 API 端点
├── config.py            # 配置管理，读取环境变量
│
├── core/                # 核心基础类
│   ├── __init__.py
│   ├── agent.py         # BaseAgent 抽象类
│   ├── context.py       # AgentContext + PipelineData
│   └── router.py        # ComplexityRouter 动态路由
│
├── agents/              # Agent 实现
│   ├── __init__.py
│   ├── kg_retriever.py  # KGRetriever Agent
│   ├── explainer.py     # Explainer Agent
│   ├── integrator.py    # Integrator Agent
│   └── pipeline.py      # AgentPipeline 编排器
│
├── tools/               # 工具层
│   ├── __init__.py
│   ├── base.py          # BaseTool 抽象类
│   ├── registry.py      # ToolRegistry 注册中心
│   ├── hybrid_search.py # HybridSearchTool 混合检索
│   ├── web_search.py    # WebSearchTool 联网搜索
│   ├── kg_extract.py    # KGExtractTool 实体抽取
│   └── doc_store.py     # DocStoreTool 文档存储
│
├── services/            # 业务服务层
│   ├── __init__.py
│   ├── chat.py          # ChatService 对话核心
│   ├── retrieval.py     # RetrievalService 检索封装
│   ├── ingest.py        # IngestService 文档导入
│   └── kg.py            # KGService 图谱管理
│
├── models/              # 数据模型
│   ├── __init__.py
│   ├── db.py            # SQLAlchemy ORM 模型
│   ├── api.py           # Pydantic API 模型
│   └── schemas.py       # 业务数据结构
│
├── llm/                 # LLM 集成
│   ├── __init__.py
│   └── client.py        # LLMClient 多提供商客户端
│
├── utils/               # 工具函数
│   ├── __init__.py
│   ├── embedding.py     # 向量嵌入服务
│   └── helpers.py       # 通用辅助函数
│
├── .env                 # 环境变量配置
├── .env.example         # 环境变量模板
└── requirements.txt     # Python 依赖
```

### 2.2 前端目录结构

```
frontend/
├── src/
│   ├── main.tsx         # 入口文件
│   ├── App.tsx          # 主应用组件
│   │
│   ├── pages/           # 页面组件
│   │   ├── ChatPage.tsx    # AI对话页面
│   │   ├── IngestPage.tsx  # 文档导入页面
│   │   ├── DocsPage.tsx    # 文档管理页面
│   │   └── SettingsPage.tsx # LLM设置页面
│   │
│   ├── components/      # 公共组件
│   │   ├── Layout.tsx      # 布局组件
│   │   ├── Sidebar.tsx     # 侧边栏
│   │   ├── ChatUI.tsx      # 对话UI组件
│   │   └── DocCard.tsx     # 文档卡片
│   │
│   ├── api/             # API 调用
│   │   └── client.ts       # API 客户端封装
│   │
│   ├── store/           # 状态管理
│   │   └── useStore.ts     # Zustand store
│   │
│   ├── types/           # 类型定义
│   │   └── index.ts        # TypeScript 类型
│   │
│   └── lib/             # 工具函数
│       └── utils.ts        # 通用工具
│
├── public/              # 静态资源
├── package.json         # 项目配置
├── vite.config.ts       # Vite 配置
├── tsconfig.json        # TypeScript 配置
└── tailwind.config.js   # Tailwind 配置
```

---

## 3. 核心模块开发指南

### 3.1 新增 Agent

**步骤：**

1. 在 `backend/agents/` 创建新 Agent 文件
2. 继承 `BaseAgent` 类
3. 实现 `execute()` 方法
4. 在 `pipeline.py` 中注册

**示例：创建 SummaryAgent**

```python
# backend/agents/summary.py

from core.agent import BaseAgent, AgentContext, AgentResult
from core.context import PipelineData

class SummaryAgent(BaseAgent):
    """总结 Agent - 生成知识摘要"""
    
    def __init__(self, llm=None):
        super().__init__(
            name="SummaryAgent",
            role="summary",
            description="生成知识点的精炼摘要"
        )
        self.llm = llm
    
    def execute(self, context: AgentContext) -> AgentResult:
        """执行摘要生成"""
        pd = context.pipeline_data
        
        # 从检索结果获取实体
        entities = pd.retrieval.entities if pd.retrieval else []
        
        # 构建 prompt
        prompt = f"请将以下知识点总结为一段精炼的描述：\n{entities}"
        
        # 调用 LLM
        response = self.llm.complete(prompt)
        
        # 存储结果
        pd.summary = response.content
        
        return AgentResult(
            success=True,
            output={"summary": response.content},
            message="摘要生成完成"
        )
    
    def get_prompt_template(self) -> str:
        return "作为知识总结专家，请将复杂内容精炼表达..."
```

**注册到 Pipeline：**

```python
# backend/agents/pipeline.py

class AgentPipeline:
    def __init__(self):
        self.agents = [
            KGRetrieverAgent(),
            ExplainerAgent(),
            IntegratorAgent(),
            SummaryAgent(),  # 新增
        ]
```

---

### 3.2 新增 Tool

**步骤：**

1. 在 `backend/tools/` 创建新 Tool 文件
2. 继承 `BaseTool` 类
3. 实现 `execute()` 方法
4. 在 `ToolRegistry` 中注册

**示例：创建 WikipediaTool**

```python
# backend/tools/wikipedia.py

from tools.base import BaseTool
import requests

class WikipediaTool(BaseTool):
    """维基百科搜索工具"""
    
    name = "wikipedia_search"
    description = "从维基百科搜索知识"
    
    def __init__(self, db=None):
        self.db = db
    
    def execute(self, query: str, lang: str = "zh") -> dict:
        """
        执行维基百科搜索
        
        参数:
        - query: 搜索关键词
        - lang: 语言 (zh/en)
        
        返回:
        {"title": "...", "summary": "...", "url": "..."}
        """
        # 维基百科 API
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{query}"
        
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            
            return {
                "success": True,
                "title": data.get("title", ""),
                "summary": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
```

**注册 Tool：**

```python
# backend/tools/__init__.py

from tools.registry import ToolRegistry
from tools.wikipedia import WikipediaTool

# 注册工具
ToolRegistry.register(WikipediaTool())
```

**在 Agent 中使用：**

```python
# Agent 绑定工具
agent.bind_tools(["wikipedia_search"])

# 执行工具
result = agent.use_tool("wikipedia_search", query="人工智能")
```

---

### 3.3 新增 LLM 提供商

**步骤：**

1. 在 `backend/llm/client.py` 中添加新提供商
2. 实现 `complete()` 方法

**示例：添加 Gemini 支持**

```python
# backend/llm/client.py

class LLMClient:
    PROVIDERS = {
        "openai": self._call_openai,
        "anthropic": self._call_anthropic,
        "deepseek": self._call_deepseek,
        "dashscope": self._call_dashscope,
        "gemini": self._call_gemini,  # 新增
    }
    
    def _call_gemini(self, prompt: str, system: str = "") -> LLMResponse:
        """调用 Gemini API"""
        import google.generativeai as genai
        
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        
        response = model.generate_content(
            f"{system}\n\n{prompt}" if system else prompt
        )
        
        return LLMResponse(
            content=response.text,
            model=self.model,
            provider="gemini"
        )
```

---

### 3.4 新增 API 端点

**步骤：**

1. 在 `backend/main.py` 中定义路由
2. 创建 Pydantic 请求模型

**示例：添加导出 API**

```python
# backend/models/api.py

from pydantic import BaseModel
from typing import Optional

class ExportRequest(BaseModel):
    format: str = "json"  # json/csv
    include_docs: bool = True
    include_kg: bool = True

class ExportResponse(BaseModel):
    file_url: str
    format: str
    created_at: str
```

```python
# backend/main.py

@app.post("/api/export", response_model=ExportResponse, tags=["export"])
def export_data(req: ExportRequest, db: Session = Depends(get_db)):
    """导出知识库数据"""
    # 导出逻辑
    if req.format == "json":
        data = {
            "nodes": [...],
            "edges": [...],
            "documents": [...]
        }
        # 保存文件
        file_path = f"exports/export_{datetime.now().strftime('%Y%m%d')}.json"
        with open(file_path, 'w') as f:
            json.dump(data, f)
    
    return ExportResponse(
        file_url=f"/downloads/{file_path}",
        format=req.format,
        created_at=datetime.now().isoformat()
    )
```

---

## 4. 数据流与调试

### 4.1 请求处理流程

```
HTTP Request
    │
    ▼
FastAPI main.py (路由解析)
    │
    ▼
Service Layer (业务逻辑)
    │
    ├── ChatService.chat()
    │       │
    │       ▼
    │   ComplexityRouter.estimate_complexity()
    │       │
    │       ├── simple → chat_fast_path()
    │       │       │
    │       │       ▼
    │       │   HybridSearchTool → LLM.complete()
    │       │
    │       └── complex → chat_pipeline()
    │               │
    │               ▼
    │           AgentPipeline.run()
    │               │
    │               ▼
    │           KGRetriever → Explainer → Integrator
    │
    ▼
Database Layer (数据持久化)
    │
    ▼
HTTP Response
```

### 4.2 调试技巧

**开启调试日志：**

```python
# backend/config.py

DEBUG = True  # 开发模式

# 日志配置
import logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
```

**Agent 执行日志：**

```python
# 在 Agent.execute() 中添加
import logging
logger = logging.getLogger(__name__)

logger.debug(f"[{self.name}] 开始执行，输入: {context.query}")
logger.debug(f"[{self.name}] 工具调用结果: {result}")
logger.info(f"[{self.name}] 执行完成，耗时: {elapsed_time}s")
```

**API 请求追踪：**

```python
# main.py 中添加中间件
from fastapi import Request
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    elapsed = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {elapsed:.2f}s")
    return response
```

---

## 5. 测试指南

### 5.1 单元测试

**测试 Agent：**

```python
# tests/test_agents.py

import pytest
from core.context import AgentContext, PipelineData
from agents.kg_retriever import KGRetrieverAgent

def test_kg_retriever():
    """测试 KG 检索 Agent"""
    agent = KGRetrieverAgent()
    agent.bind_tools(["hybrid_search"])
    
    context = AgentContext(
        pipeline_data=PipelineData(query="什么是RAG?")
    )
    
    result = agent.execute(context)
    
    assert result.success == True
    assert len(result.output.get("entities", [])) > 0
```

**测试 Tool：**

```python
# tests/test_tools.py

def test_hybrid_search():
    """测试混合检索工具"""
    tool = HybridSearchTool(db=mock_db)
    result = tool.execute("RAG")
    
    assert result["success"] == True
    assert "entities" in result
```

### 5.2 API 测试

```python
# tests/test_api.py

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_chat_api():
    """测试对话 API"""
    response = client.post("/api/chat", json={"message": "什么是RAG?"})
    
    assert response.status_code == 200
    data = response.json()
    assert "response" in data["data"]
    assert data["data"]["path"] in ["fast", "pipeline"]

def test_websearch_api():
    """测试联网搜索 API"""
    response = client.post("/api/websearch", json={"query": "AI论文"})
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data["data"]
```

### 5.3 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_agents.py -v

# 生成覆盖率报告
pytest tests/ --cov=backend --cov-report=html
```

---

## 6. 前端开发指南

### 6.1 组件开发规范

**页面组件结构：**

```typescript
// src/pages/ExamplePage.tsx

import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'

export default function ExamplePage() {
  // 1. 状态管理
  const [searchTerm, setSearchTerm] = useState('')
  
  // 2. 数据请求
  const { data, isLoading } = useQuery({
    queryKey: ['docs', searchTerm],
    queryFn: () => api.getDocs(searchTerm)
  })
  
  // 3. 事件处理
  const handleSearch = (term: string) => {
    setSearchTerm(term)
  }
  
  // 4. 渲染
  return (
    <div className="p-4">
      {/* 搜索框 */}
      <SearchInput onSearch={handleSearch} />
      
      {/* 数据展示 */}
      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <DocList docs={data} />
      )}
    </div>
  )
}
```

### 6.2 API 调用封装

```typescript
// src/api/client.ts

import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8001',
  timeout: 30000,
})

// 对话 API
export const chatApi = {
  chat: (message: string, conversationId?: number) =>
    client.post('/api/chat', { message, conversation_id: conversationId }),
  
  fastPath: (message: string) =>
    client.post('/api/chat/fast', { message }),
  
  pipeline: (message: string) =>
    client.post('/api/chat/pipeline', { message }),
}

// 文档 API
export const docsApi = {
  list: (params?: { search?: string; limit?: number }) =>
    client.get('/api/docs', { params }),
  
  ingest: (title: string, content: string, tags?: string[]) =>
    client.post('/api/ingest', { title, content, tags }),
  
  delete: (id: number) =>
    client.delete(`/api/docs/${id}`),
}

// KG API
export const kgApi = {
  search: (query: string, mode?: string) =>
    client.get('/api/kg/search', { params: { q: query, mode } }),
  
  getNodes: (params?: { type?: string; search?: string }) =>
    client.get('/api/kg/nodes', { params }),
}
```

### 6.3 状态管理

```typescript
// src/store/useStore.ts

import { create } from 'zustand'

interface AppState {
  // UI 状态
  activeTab: 'chat' | 'docs' | 'kg' | 'settings'
  darkMode: boolean
  
  // 对话状态
  currentConversationId: number | null
  messages: Message[]
  
  // 操作方法
  setActiveTab: (tab: string) => void
  setDarkMode: (mode: boolean) => void
  addMessage: (msg: Message) => void
  clearMessages: () => void
}

export const useStore = create<AppState>((set) => ({
  activeTab: 'chat',
  darkMode: false,
  currentConversationId: null,
  messages: [],
  
  setActiveTab: (tab) => set({ activeTab: tab }),
  setDarkMode: (mode) => set({ darkMode: mode }),
  addMessage: (msg) => set((state) => ({ 
    messages: [...state.messages, msg] 
  })),
  clearMessages: () => set({ messages: [] }),
}))
```

---

## 7. 代码规范

### 7.1 Python 代码规范

- 使用 PEP 8 风格
- 类型注解必须
- 文件头注释说明模块用途
- 函数文档字符串

```python
# 示例规范代码
from typing import Dict, Any, List, Optional

def process_query(
    query: str,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    处理用户查询
    
    Args:
        query: 用户输入的查询字符串
        context: 可选的上下文信息
    
    Returns:
        处理结果字典，包含 entities, relations 等
    """
    ...
```

### 7.2 TypeScript 代码规范

- 使用 ESLint + Prettier
- 接口定义类型
- 组件命名 PascalCase
- 函数命名 camelCase

```typescript
// 示例规范代码
interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

const formatMessage = (msg: Message): string => {
  return `${msg.role}: ${msg.content}`
}
```

---

## 8. Git 工作流

### 8.1 分支管理

```
main           # 主分支，稳定版本
  │
  ├── develop  # 开发分支
  │     │
  │     ├── feature/xxx  # 功能分支
  │     ├── fix/xxx      # 修复分支
  │     └── refactor/xxx # 重构分支
```

### 8.2 提交规范

```
feat: 新增功能
fix: 修复问题
docs: 文档更新
refactor: 代码重构
test: 测试相关
chore: 其他变更

示例：
feat: 新增 WikipediaTool 联网搜索工具
fix: 修复 KG 检索结果去重问题
docs: 更新 API 接口文档
```

---

## 9. 常见问题与解决方案

### 9.1 LLM 调用超时

```python
# 设置超时和重试
from httpx import Timeout

timeout = Timeout(60.0, connect=10.0)

# 重试机制
max_retries = 3
for i in range(max_retries):
    try:
        response = llm.complete(prompt)
        break
    except TimeoutError:
        if i == max_retries - 1:
            raise
        time.sleep(2)
```

### 9.2 数据库连接问题

```python
# 连接池配置
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    pool_recycle=3600,
    pool_pre_ping=True,  # 连接健康检查
)
```

### 9.3 向量嵌入内存溢出

```python
# 分批处理
batch_size = 100
for i in range(0, len(nodes), batch_size):
    batch = nodes[i:i+batch_size]
    embeddings = embedding_service.embed_batch(batch)
    # 存储...
```

---

## 10. 扩展参考

### 10.1 Agent 扩展参考

| Agent | 功能 | 输入 | 输出 |
|-------|------|------|------|
| KGRetriever | KG检索 | query | RetrievalData |
| Explainer | 通俗化 | entities | ExplanationData |
| Integrator | 整合生成 | retrieval + explanation | IntegrationData |
| SummaryAgent | 摘要生成 | entities | SummaryData |
| ValidatorAgent | 验证检查 | answer | ValidationResult |

### 10.2 Tool 扩展参考

| Tool | 功能 | 参数 |
|------|------|------|
| HybridSearchTool | 混合检索 | query, top_k |
| WebSearchTool | 联网搜索 | query, save |
| KGExtractTool | 实体抽取 | text |
| WikipediaTool | 维基搜索 | query, lang |
| ArxivTool | 论文搜索 | query |

### 10.3 API 扩展参考

| API | 功能 | 路径 |
|-----|------|------|
| ExportAPI | 数据导出 | `/api/export` |
| StatsAPI | 统计数据 | `/api/stats` |
| BatchAPI | 批量操作 | `/api/batch` |