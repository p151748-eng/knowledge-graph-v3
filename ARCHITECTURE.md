# KG-Agent System v2 架构设计文档

## 1. 系统概述

KG-Agent System v2 是一个面向个人学习的智能知识库系统，采用 **3-Agent 流水线** + **动态路由** 架构设计。

**设计理念：**
- 简洁高效：精简的 3-Agent 架构，移除冗余功能
- 动态路由：根据问题复杂度自动选择最优路径
- 混合检索：RAG + KG 深度结合，三重检索保障
- 知识沉淀：联网搜索结果自动存储，持续积累

---

## 2. 整体架构

### 2.1 架构分层图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI REST API                            │
│                     (main.py - 15个核心端点)                        │
│                                                                     │
│   /api/chat  /api/websearch  /api/ingest  /api/docs  /api/kg        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Services Layer                              │
│                                                                     │
│   ChatService    RetrievalService    IngestService    KGService     │
│   (对话核心)      (检索封装)          (文档导入)        (图谱管理)    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Dynamic Router Layer                           │
│                                                                     │
│                    ComplexityRouter                                 │
│                                                                     │
│          estimate_complexity(query) → "simple" | "complex"          │
│                                                                     │
│              simple ──→ FastPath (~2秒)                             │
│              complex ──→ 3-Agent Pipeline (~5-8秒)                  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
┌────────────────────────────┐    ┌────────────────────────────────────┐
│      Fast Path             │    │      3-Agent Pipeline              │
│  (简单问题快速响应)         │    │     (复杂问题完整处理)             │
│                            │    │                                    │
│  ┌─────────────────────┐   │    │  ┌──────────────────────────────┐ │
│  │ HybridSearchTool    │   │    │  │ Agent 1: KGRetriever         │ │
│  │ (混合检索)          │   │    │  │ 工具: HybridSearchTool       │ │
│  └─────────────────────┘   │    │  │ 输出: RetrievalData          │ │
│            │               │    │  └──────────────────────────────┘ │
│            ▼               │    │                │                  │
│  ┌─────────────────────┐   │    │                ▼                  │
│  │ LLM Direct Generate │   │    │  ┌──────────────────────────────┐ │
│  │ (直接生成回答)      │   │    │  │ Agent 2: Explainer           │ │
│  └─────────────────────┘   │    │  │ 功能: 术语通俗化             │ │
│                            │    │  │ 输出: ExplanationData        │ │
│      总耗时: ~2秒          │    │  └──────────────────────────────┘ │
│                            │    │                │                  │
│                            │    │                ▼                  │
│                            │    │  ┌──────────────────────────────┐ │
│                            │    │  │ Agent 3: Integrator          │ │
│                            │    │  │ 功能: 整合生成回答           │ │
│                            │    │  │ 输出: IntegrationData        │ │
│                            │    │  └──────────────────────────────┘ │
│                            │    │                                    │
│                            │    │      总耗时: ~5-8秒                │
└────────────────────────────┘    └────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Tools Layer                                 │
│                                                                     │
│  HybridSearchTool │ WebSearchTool │ KGExtractTool │ DocStoreTool   │
│  (混合检索)        (联网搜索)      (实体抽取)      (文档存储)        │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Tool Registry                               │ │
│  │   全局工具注册表，Agent 通过 bind_tools() 获取所需工具         │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
┌────────────────────────────┐    ┌────────────────────────────────────┐
│        LLM Layer           │    │         Database Layer             │
│                            │    │                                    │
│  ┌──────────────────────┐  │    │  ┌──────────────────────────────┐  │
│  │     LLMClient        │  │    │  │     SQLAlchemy ORM           │  │
│  │                      │  │    │  │                              │  │
│  │  多提供商支持:        │  │    │  │  Tables:                     │  │
│  │  - OpenAI            │  │    │  │  - nodes (KG节点)            │  │
│  │  - Anthropic         │  │    │  │  - edges (KG关系)            │  │
│  │  - DeepSeek          │  │    │  │  - documents (文档库)         │  │
│  │  - DashScope         │  │    │  │  - conversations (对话)       │  │
│  │                      │  │    │  │                              │  │
│  │  统一接口:           │  │    │  │  SessionLocal                │  │
│  │  complete(prompt)    │  │    │  │  (数据库会话工厂)             │  │
│  │  complete_json()     │  │    │  └──────────────────────────────┘  │
│  └──────────────────────┘  │    │                                    │
└────────────────────────────┘    └────────────────────────────────────┘
                    │                             │
                    └──────────────┬──────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         MySQL Database                              │
│                                                                     │
│              kg_agent (UTF8MB4 编码)                                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块设计

### 3.1 Dynamic Router Layer（动态路由层）

#### ComplexityRouter

```python
# core/router.py

class ComplexityRouter:
    """问题复杂度路由器"""
    
    COMPLEX_KEYWORDS = [
        "分析", "对比", "比较", "如何", "为什么",
        "区别", "联系", "关系", "结合", "整合",
        "评价", "总结", "归纳", "推导", "论证"
    ]
    
    def estimate_complexity(self, query: str) -> str:
        """
        判断问题复杂度
        
        返回值:
        - "simple": 快速路径
        - "complex": 完整流水线
        
        判断规则:
        1. 长度 < 20 且无复杂关键词 → simple
        2. 包含复杂关键词 → complex
        3. 多实体查询（提及多个概念）→ complex
        """
        # 规则 1: 长度判断
        if len(query) < 20:
            for kw in self.COMPLEX_KEYWORDS:
                if kw in query:
                    return "complex"
            return "simple"
        
        # 规则 2: 关键词判断
        for kw in self.COMPLEX_KEYWORDS:
            if kw in query:
                return "complex"
        
        # 规则 3: 多实体判断
        entities = self._detect_entities(query)
        if len(entities) >= 2:
            return "complex"
        
        return "simple"
```

**复杂度判断示例：**

| 问题 | 复杂度 | 路径 |
|------|--------|------|
| "什么是RAG?" | simple | FastPath |
| "OpenAI的CEO是谁?" | simple | FastPath |
| "RAG和知识图谱如何结合?" | complex | 3-Agent |
| "分析Agent和LLM的区别" | complex | 3-Agent |

---

### 3.2 3-Agent Pipeline（3-Agent流水线）

#### 流水线架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                        用户问题输入                                   │
│                     "RAG和知识图谱如何结合？"                         │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Agent 1: KGRetriever                                                │
│  ─────────────────────                                               │
│                                                                     │
│  职责: 从知识图谱检索相关实体、关系和文档                             │
│                                                                     │
│  工具绑定:                                                           │
│  - HybridSearchTool (混合检索)                                       │
│  - GraphTraversalTool (图遍历)                                       │
│                                                                     │
│  执行流程:                                                           │
│  1. 关键词匹配 Node.name ILIKE                                       │
│  2. 向量语义检索 EmbeddingService                                    │
│  3. 图扩展 1-hop 邻居节点                                            │
│  4. 合并去重，构建上下文                                              │
│                                                                     │
│  输出: RetrievalData                                                 │
│  {                                                                  │
│    entities: [{id, name, type, description, score}],               │
│    relations: [{source, relation, target}],                        │
│    context_text: "【相关实体】RAG(概念): ...",                      │
│    doc_chunks: [{doc_id, chunk, score}]                            │
│  }                                                                  │
│                                                                     │
│  耗时: ~1-2秒                                                        │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Agent 2: Explainer                                                  │
│  ─────────────────────                                               │
│                                                                     │
│  职责: 将专业术语通俗化，添加类比解释                                 │
│                                                                     │
│  输入: RetrievalData.entities                                       │
│                                                                     │
│  LLM Prompt:                                                        │
│  "将以下专业术语用通俗易懂的语言解释，并提供类比：                    │
│   - RAG: 检索增强生成                                                │
│   - Knowledge Graph: 知识图谱                                        │
│   ..."                                                              │
│                                                                     │
│  输出: ExplanationData                                               │
│  {                                                                  │
│    explanations: [                                                  │
│      {term: "RAG", simple: "像个智能图书馆助手", analogy: "..."},   │
│      {term: "KG", simple: "像知识的关系网", analogy: "..."}        │
│    ],                                                               │
│    glossary: {"RAG": "检索增强生成...", "KG": "知识图谱..."}        │
│  }                                                                  │
│                                                                     │
│  耗时: ~1-2秒                                                        │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Agent 3: Integrator                                                 │
│  ─────────────────────                                               │
│                                                                     │
│  职责: 整合检索结果和解释，生成最终回答                               │
│                                                                     │
│  输入:                                                              │
│  - RetrievalData (原始知识)                                         │
│  - ExplanationData (通俗解释)                                       │
│                                                                     │
│  LLM Prompt:                                                        │
│  "基于以下信息，回答用户问题，要求：                                  │
│   1. 结合原始知识和通俗解释                                          │
│   2. 结构化输出，条理清晰                                            │
│   3. 提供具体示例或类比                                              │
│   4. 标注信息来源                                                    │
│                                                                     │
│   【原始知识】{context_text}                                         │
│   【通俗解释】{explanations}                                         │
│   【用户问题】{query}"                                               │
│                                                                     │
│  输出: IntegrationData                                               │
│  {                                                                  │
│    answer: "RAG和知识图谱可以这样结合...",                           │
│    sources: [{node_id, node_name, doc_id}],                        │
│    confidence: 0.85,                                                │
│    key_points: ["要点1", "要点2"]                                   │
│  }                                                                  │
│                                                                     │
│  耗时: ~2-3秒                                                        │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        最终响应输出                                   │
│  {                                                                  │
│    response: "RAG和知识图谱可以从三个层面结合...",                   │
│    sources: ["RAG节点", "KG节点", "文档#12"],                        │
│    confidence: 0.85,                                                │
│    processing_time: 5.2s,                                           │
│    path: "pipeline"                                                 │
│  }                                                                  │
└──────────────────────────────────────────────────────────────────────┘

总耗时: ~5-8秒
```

#### Agent 基类设计

```python
# core/agent.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum

class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class AgentResult:
    """Agent执行结果"""
    success: bool
    output: Any
    message: str = ""
    confidence: float = 0.5
    errors: List[str] = field(default_factory=list)

class BaseAgent(ABC):
    """Agent抽象基类"""
    
    def __init__(self, name: str, role: str, description: str = ""):
        self.name = name
        self.role = role
        self.description = description
        self.status = AgentStatus.IDLE
        self._tools: Dict[str, Any] = {}
    
    def bind_tools(self, tool_names: List[str]):
        """绑定工具"""
        from tools.registry import ToolRegistry
        self._tools = ToolRegistry.for_agent(tool_names)
    
    def use_tool(self, name: str, **kwargs) -> Dict[str, Any]:
        """执行工具"""
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not bound"}
        return tool.execute(**kwargs)
    
    @abstractmethod
    def execute(self, context: AgentContext) -> AgentResult:
        """执行Agent逻辑（子类实现）"""
        pass
    
    def run(self, context: AgentContext) -> AgentResult:
        """运行Agent"""
        self.status = AgentStatus.WORKING
        try:
            result = self.execute(context)
            self.status = AgentStatus.COMPLETED
            return result
        except Exception as e:
            self.status = AgentStatus.ERROR
            return AgentResult(success=False, output=None, errors=[str(e)])
```

---

### 3.3 Tools Layer（工具层）

#### HybridSearchTool（混合检索工具）

```python
# tools/hybrid_search.py

class HybridSearchTool(BaseTool):
    """RAG + KG 混合检索工具"""
    
    name = "hybrid_search"
    description = "执行关键词、向量、图扩展三重混合检索"
    
    def execute(self, query: str, top_k: int = 10) -> dict:
        """
        执行混合检索
        
        参数:
        - query: 搜索查询
        - top_k: 返回结果数量
        
        返回:
        {
            "entities": [...],  # 命中实体
            "relations": [...], # 相关关系
            "doc_chunks": [...],# 文档片段
            "scores": {...}     # 各路得分
        }
        """
        results = {
            "keyword_hits": [],
            "semantic_hits": [],
            "graph_hits": []
        }
        
        # 1. 关键词匹配（快速，~50ms）
        results["keyword_hits"] = self._keyword_search(query)
        
        # 2. 向量语义检索（精准，~200ms）
        results["semantic_hits"] = self._semantic_search(query)
        
        # 3. 图扩展（关联，~100ms）
        seed_ids = [h["id"] for h in results["keyword_hits"] + results["semantic_hits"]]
        results["graph_hits"] = self._graph_expansion(seed_ids, hop=1)
        
        # 4. 合并去重排序
        merged = self._merge_and_rank(results)
        
        return {
            "entities": merged[:top_k],
            "relations": self._get_relations(merged),
            "doc_chunks": self._get_doc_chunks(merged)
        }
    
    def _keyword_search(self, query: str) -> List[dict]:
        """关键词模糊匹配"""
        words = query.split()
        # SQL: Node.name ILIKE %word%
        ...
    
    def _semantic_search(self, query: str) -> List[dict]:
        """向量语义检索"""
        query_embedding = self.embedding_service.embed(query)
        # 计算与所有节点的余弦相似度
        ...
    
    def _graph_expansion(self, node_ids: List[int], hop: int = 1) -> List[dict]:
        """K-hop 图扩展"""
        # 查询 Edge 表，获取邻居节点
        ...
    
    def _merge_and_rank(self, results: dict) -> List[dict]:
        """
        合并排序策略:
        - keyword 权重: 0.3
        - semantic 权重: 0.5
        - graph 权重: 0.2
        """
        ...
```

#### WebSearchTool（联网搜索工具）

```python
# tools/web_search.py

from duckduckgo_search import DDGS

class WebSearchTool(BaseTool):
    """DuckDuckGo 联网搜索工具"""
    
    name = "web_search"
    description = "联网搜索并自动沉淀知识"
    
    def execute(self, query: str, max_results: int = 5, save: bool = True) -> dict:
        """
        执行联网搜索
        
        参数:
        - query: 搜索查询
        - max_results: 最大结果数
        - save: 是否保存到知识库
        
        返回:
        {
            "results": [{title, url, snippet}],
            "saved_to_kg": bool,
            "saved_to_docs": bool,
            "nodes_created": int,
            "docs_created": int
        }
        """
        # 1. DuckDuckGo 搜索
        with DDGS() as ddgs:
            search_results = list(ddgs.text(query, max_results=max_results))
        
        # 2. 知识沉淀
        if save:
            # 存入 KG
            kg_result = self._save_to_kg(search_results, query)
            # 存入文档库
            doc_result = self._save_to_docs(search_results, query)
        
        return {
            "results": search_results,
            "saved_to_kg": save,
            "saved_to_docs": save,
            "nodes_created": kg_result.get("nodes_created", 0),
            "docs_created": doc_result.get("docs_created", 0)
        }
    
    def _save_to_kg(self, results: List[dict], source_query: str) -> dict:
        """
        存入知识图谱:
        1. 从搜索结果抽取实体
        2. 创建 Node 记录
        3. 创建 Edge 记录（实体间关系）
        """
        # 使用 LLM 抽取实体
        entities = self._extract_entities(results)
        # 存入数据库
        ...
    
    def _save_to_docs(self, results: List[dict], source_query: str) -> dict:
        """
        存入文档库:
        1. 合并搜索结果为文档
        2. 创建 Document 记录
        """
        ...
```

---

### 3.4 Services Layer（服务层）

#### ChatService

```python
# services/chat.py

class ChatService:
    """对话服务 - 核心业务逻辑"""
    
    def __init__(self, db: Session, llm: LLMClient):
        self.db = db
        self.llm = llm
        self.router = ComplexityRouter()
        self.retrieval = RetrievalService(db, llm)
    
    def chat(self, message: str, conversation_id: Optional[int] = None) -> dict:
        """
        主对话入口 - 自动路由
        
        流程:
        1. 判断复杂度
        2. 选择路径
        3. 执行并返回
        """
        complexity = self.router.estimate_complexity(message)
        
        if complexity == "simple":
            return self.chat_fast_path(message, conversation_id)
        else:
            return self.chat_pipeline(message, conversation_id)
    
    def chat_fast_path(self, message: str, conversation_id: Optional[int]) -> dict:
        """
        快速路径 - 单次检索 + LLM生成
        
        步骤:
        1. HybridSearchTool 检索
        2. 构建上下文
        3. LLM 直接生成
        """
        # 1. 检索
        retrieval = HybridSearchTool(self.db).execute(message)
        
        # 2. 构建上下文
        context = self._build_context(retrieval)
        
        # 3. LLM 生成
        system_prompt = f"基于以下知识回答用户问题：\n{context}"
        answer = self.llm.complete(message, system_prompt).content
        
        # 4. 保存对话
        conv = self._save_conversation(message, answer, conversation_id)
        
        return {
            "response": answer,
            "sources": retrieval["entities"],
            "conversation_id": conv.id,
            "path": "fast",
            "processing_time": "~2s"
        }
    
    def chat_pipeline(self, message: str, conversation_id: Optional[int]) -> dict:
        """
        完整流水线 - 3-Agent协作
        
        步骤:
        1. 创建 PipelineData
        2. 执行 KGRetriever
        3. 执行 Explainer
        4. 执行 Integrator
        """
        # 1. 创建上下文
        pipeline_data = PipelineData(query=message)
        context = AgentContext(pipeline_data=pipeline_data)
        
        # 2. 执行流水线
        pipeline = AgentPipeline()
        result = pipeline.run(context)
        
        # 3. 返回结果
        return {
            "response": pipeline_data.integration.answer,
            "sources": pipeline_data.integration.sources,
            "explanations": pipeline_data.explanation.explanations,
            "conversation_id": conversation_id,
            "path": "pipeline",
            "processing_time": "~5-8s"
        }
```

#### RetrievalService

```python
# services/retrieval.py

class RetrievalService:
    """检索服务 - 封装混合检索逻辑"""
    
    def __init__(self, db: Session, llm: LLMClient):
        self.db = db
        self.embedding = EmbeddingService(llm)
        self.hybrid_search = HybridSearchTool(db, self.embedding)
    
    def search(self, query: str, mode: str = "hybrid") -> dict:
        """
        执行检索
        
        mode:
        - "keyword": 仅关键词
        - "semantic": 仅向量
        - "hybrid": 混合检索
        """
        if mode == "hybrid":
            return self.hybrid_search.execute(query)
        elif mode == "keyword":
            return self._keyword_only(query)
        elif mode == "semantic":
            return self._semantic_only(query)
```

---

## 4. 数据模型设计

### 4.1 数据库表结构

```sql
-- 知识图谱节点
CREATE TABLE nodes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(32) NOT NULL DEFAULT 'entity',  -- entity/concept/document
    description TEXT,
    embedding TEXT,                               -- JSON 存储向量
    source_doc_ids JSON,                          -- 来源文档ID列表
    confidence FLOAT DEFAULT 0.8,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_name (name),
    INDEX idx_type (type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 知识图谱关系
CREATE TABLE edges (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_id INT NOT NULL,
    target_id INT NOT NULL,
    relation VARCHAR(255) NOT NULL,
    confidence FLOAT DEFAULT 0.8,
    source_doc_ids JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
    INDEX idx_source (source_id),
    INDEX idx_target (target_id),
    INDEX idx_relation (relation),
    UNIQUE KEY uk_edge (source_id, target_id, relation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 文档库
CREATE TABLE documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(512) DEFAULT 'manual',        -- manual/web_search
    source_url VARCHAR(512),                      -- 联网搜索来源URL
    tags JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 对话
CREATE TABLE conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(512),
    messages JSON NOT NULL,                       -- [{role, content, timestamp}]
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.2 数据流设计

```
文档导入流程:
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 用户上传    │ -> │ LLM抽取     │ -> │ 创建Node    │ -> │ 创建Edge    │
│ 文档/文本   │    │ 实体/关系   │    │ 存入KG      │    │ 连接实体    │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘

联网搜索流程:
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ DuckDuckGo  │ -> │ LLM抽取     │ -> │ 存入KG      │ -> │ 存入Docs    │
│ 搜索        │    │ 实体        │    │ 结构化      │    │ 原文        │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘

对话检索流程:
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 用户提问    │ -> │ 关键词匹配  │ -> │ 向量检索    │ -> │ 图扩展      │
│             │    │ Node.name   │    │ embedding   │    │ 1-hop       │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                            │
                                                            ▼
                                         ┌─────────────────────────────┐
                                         │ 合并排序 → 构建上下文 → LLM │
                                         └─────────────────────────────┘
```

---

## 5. 性能优化设计

### 5.1 响应时间优化

| 路径 | 优化点 | 目标时间 |
|------|--------|--------|
| FastPath | 单次检索+单次LLM调用 | ~2秒 |
| Pipeline | Agent串行执行，无并行 | ~5-8秒 |

### 5.2 检索优化

| 技术 | 优化效果 |
|------|--------|
| 关键词索引 | Node.name 索引，匹配 ~50ms |
| 向量缓存 | 预计算 embedding，避免重复生成 |
| 图扩展限制 | hop=1，限制 max_nodes=20 |
| 结果去重 | 按 ID 去重，避免重复计算 |

---

## 6. 扩展设计

### 6.1 Agent 扩展

新增 Agent 只需：
1. 继承 `BaseAgent`
2. 实现 `execute()` 方法
3. 在 `AgentPipeline` 中注册

### 6.2 Tool 扩展

新增 Tool 只需：
1. 继承 `BaseTool`
2. 实现 `execute()` 方法
3. 在 `ToolRegistry` 中注册

### 6.3 LLM 提供商扩展

新增 LLM 只需：
1. 在 `LLMClient` 中添加提供商
2. 实现统一的 `complete()` 接口

---

## 7. 架构演进规划

### v1.1 版本

- 新增长期记忆系统
- 新增知识图谱可视化展示

### v2.0 版本

- 引入向量数据库（pgvector/Milvus）
- 多用户支持
- 权限系统