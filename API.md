# KG-Agent System v2 API 接口文档

## 1. API 概述

### 1.1 基本信息

| 项目 | 说明 |
|------|------|
| **Base URL** | `http://localhost:8001` |
| **API 版本** | v1.0 |
| **数据格式** | JSON |
| **认证方式** | 无（单用户系统） |

### 1.2 通用响应格式

**成功响应：**
```json
{
  "success": true,
  "data": { ... },
  "message": "操作成功"
}
```

**错误响应：**
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述",
    "details": { ... }
  }
}
```

### 1.3 API 分类

| 分类 | 端点前缀 | 功能 |
|------|----------|------|
| 对话 | `/api/chat` | AI对话问答 |
| 联网搜索 | `/api/websearch` | 网络搜索与知识沉淀 |
| 文档管理 | `/api/docs` | 文档导入与管理 |
| 知识图谱 | `/api/kg` | KG节点与关系管理 |
| 对话管理 | `/api/convs` | 对话历史管理 |
| 系统设置 | `/api/settings` | LLM配置 |
| 健康检查 | `/api/health` | 系统状态 |

---

## 2. 对话 API

### 2.1 POST /api/chat

**描述：** AI对话问答（自动路由）

**请求体：**
```json
{
  "message": "什么是RAG?",
  "conversation_id": null,      // 可选，继续已有对话
  "force_path": null            // 可选，强制路径 "fast"/"pipeline"
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "response": "RAG（Retrieval-Augmented Generation）是一种结合检索和生成的AI技术...",
    "sources": [
      {"id": 1, "name": "RAG", "type": "concept", "description": "..."},
      {"id": 2, "name": "LLM", "type": "concept", "description": "..."}
    ],
    "explanations": [            // 仅pipeline路径有
      {"term": "RAG", "simple": "像给AI配备了图书馆", "analogy": "..."}
    ],
    "conversation_id": 1,
    "path": "fast",              // "fast" 或 "pipeline"
    "processing_time": "2.1s",
    "confidence": 0.85
  }
}
```

**路由逻辑：**
```
请求 → ComplexityRouter → 
  simple → FastPath (~2秒)
  complex → 3-Agent Pipeline (~5-8秒)
```

**示例：**

```bash
# 简单问题（自动走快速路径）
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "什么是RAG?"}'

# 复杂问题（自动走完整流水线）
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "RAG和知识图谱如何结合，各自的优势是什么？"}'

# 强制指定路径
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "什么是RAG?", "force_path": "pipeline"}'
```

---

### 2.2 POST /api/chat/fast

**描述：** 强制使用快速路径

**请求体：**
```json
{
  "message": "OpenAI的CEO是谁?",
  "conversation_id": null
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "response": "OpenAI的现任CEO是Sam Altman...",
    "sources": [{"id": 5, "name": "OpenAI", "type": "entity"}],
    "conversation_id": 2,
    "path": "fast",
    "processing_time": "1.8s"
  }
}
```

---

### 2.3 POST /api/chat/pipeline

**描述：** 强制使用3-Agent流水线

**请求体：**
```json
{
  "message": "分析Agent技术的发展趋势和挑战",
  "conversation_id": null
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "response": "Agent技术的发展可以从三个维度分析...",
    "sources": [
      {"id": 10, "name": "Agent", "type": "concept"},
      {"id": 11, "name": "ReAct", "type": "concept"}
    ],
    "explanations": [
      {"term": "Agent", "simple": "能自主行动的AI助手", "analogy": "像智能秘书"},
      {"term": "ReAct", "simple": "思考+行动的循环模式", "analogy": "..."}
    ],
    "conversation_id": 3,
    "path": "pipeline",
    "processing_time": "6.2s",
    "confidence": 0.92
  }
}
```

---

## 3. 联网搜索 API

### 3.1 POST /api/websearch

**描述：** DuckDuckGo联网搜索，结果自动存入KG和文档库

**请求体：**
```json
{
  "query": "最新AI Agent研究论文",
  "max_results": 5,           // 可选，默认5
  "save_to_kg": true,         // 可选，默认true
  "save_to_docs": true        // 可选，默认true
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "title": "ReAct: Synergizing Reasoning and Acting...",
        "url": "https://arxiv.org/abs/...",
        "snippet": "这篇论文提出了ReAct框架..."
      },
      {
        "title": "Toolformer: Language Models Can Teach...",
        "url": "https://arxiv.org/abs/...",
        "snippet": "Toolformer让LLM自主学习使用工具..."
      }
    ],
    "saved_to_kg": true,
    "saved_to_docs": true,
    "nodes_created": 8,        // 新创建的KG节点数
    "edges_created": 5,        // 新创建的关系数
    "docs_created": 1          // 新创建的文档数
  }
}
```

**知识沉淀说明：**

| 存储位置 | 内容 | 用途 |
|----------|------|------|
| KG (nodes) | 抽取的实体、概念 | 后续KG检索 |
| KG (edges) | 实体间关系 | 关联扩展 |
| Documents | 合并的搜索结果原文 | RAG检索 |

**示例：**

```bash
# 联网搜索并自动沉淀
curl -X POST http://localhost:8001/api/websearch \
  -H "Content-Type: application/json" \
  -d '{"query": "2024年大模型发展趋势"}'

# 仅搜索不保存
curl -X POST http://localhost:8001/api/websearch \
  -H "Content-Type: application/json" \
  -d '{"query": "GPT-4技术细节", "save_to_kg": false, "save_to_docs": false}'
```

---

## 4. 文档管理 API

### 4.1 POST /api/ingest

**描述：** 导入文本内容，自动抽取实体构建KG

**请求体：**
```json
{
  "title": "RAG技术概述",
  "content": "RAG（检索增强生成）是一种结合外部知识库和LLM的技术...",
  "source": "manual",
  "tags": ["RAG", "LLM", "技术"]
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "document_id": 10,
    "nodes_created": 5,
    "edges_created": 3,
    "entities_extracted": [
      {"name": "RAG", "type": "concept"},
      {"name": "知识库", "type": "entity"},
      {"name": "LLM", "type": "concept"}
    ],
    "message": "文档导入成功，创建了5个节点和3个关系"
  }
}
```

---

### 4.2 POST /api/ingest/file

**描述：** 上传文件导入（支持 Markdown、TXT）

**请求：** multipart/form-data

| 参数 | 类型 | 说明 |
|------|------|------|
| file | File | 文件（.md/.txt） |
| source | String | 来源标识 |
| tags | String | 标签（逗号分隔） |

**响应：**
```json
{
  "success": true,
  "data": {
    "document_id": 11,
    "nodes_created": 8,
    "edges_created": 6,
    "message": "文件导入成功"
  }
}
```

**示例：**

```bash
curl -X POST http://localhost:8001/api/ingest/file \
  -F "file=@./paper.md" \
  -F "source=论文" \
  -F "tags=AI,Agent"
```

---

### 4.3 GET /api/docs

**描述：** 获取文档列表

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| search | String | 搜索关键词 |
| source | String | 来源筛选 |
| limit | Int | 返回数量（默认20） |
| offset | Int | 偏移量 |

**响应：**
```json
{
  "success": true,
  "data": {
    "documents": [
      {
        "id": 1,
        "title": "RAG技术概述",
        "content_preview": "RAG（检索增强生成）...",
        "source": "manual",
        "tags": ["RAG", "LLM"],
        "created_at": "2024-01-15T10:00:00"
      }
    ],
    "total": 15,
    "limit": 20,
    "offset": 0
  }
}
```

---

### 4.4 GET /api/docs/{doc_id}

**描述：** 获取单个文档详情

**响应：**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "title": "RAG技术概述",
    "content": "完整内容...",
    "source": "manual",
    "source_url": null,
    "tags": ["RAG", "LLM"],
    "related_nodes": [        // 关联的KG节点
      {"id": 5, "name": "RAG"},
      {"id": 6, "name": "知识库"}
    ],
    "created_at": "2024-01-15T10:00:00"
  }
}
```

---

### 4.5 DELETE /api/docs/{doc_id}

**描述：** 删除文档（关联节点不删除）

**响应：**
```json
{
  "success": true,
  "message": "文档已删除"
}
```

---

## 5. 知识图谱 API

### 5.1 GET /api/kg/nodes

**描述：** 获取KG节点列表

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| search | String | 搜索关键词 |
| type | String | 类型筛选（entity/concept/document） |
| limit | Int | 返回数量 |

**响应：**
```json
{
  "success": true,
  "data": {
    "nodes": [
      {
        "id": 1,
        "name": "RAG",
        "type": "concept",
        "description": "检索增强生成技术",
        "source_doc_ids": [1, 5],
        "confidence": 0.9,
        "created_at": "2024-01-15T10:00:00"
      }
    ],
    "total": 50
  }
}
```

---

### 5.2 POST /api/kg/nodes

**描述：** 手动创建KG节点

**请求体：**
```json
{
  "name": "Transformer",
  "type": "concept",
  "description": "一种基于注意力机制的神经网络架构",
  "source_doc_ids": []
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "id": 51,
    "name": "Transformer",
    "type": "concept",
    "message": "节点创建成功"
  }
}
```

---

### 5.3 PUT /api/kg/nodes/{node_id}

**描述：** 更新KG节点

**请求体：**
```json
{
  "name": "Transformer架构",
  "description": "更新后的描述..."
}
```

---

### 5.4 DELETE /api/kg/nodes/{node_id}

**描述：** 删除KG节点（关联边级联删除）

---

### 5.5 GET /api/kg/edges

**描述：** 获取KG关系列表

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| source_id | Int | 源节点ID |
| target_id | Int | 目标节点ID |
| relation | String | 关系类型 |

**响应：**
```json
{
  "success": true,
  "data": {
    "edges": [
      {
        "id": 1,
        "source_id": 1,
        "target_id": 2,
        "relation": "依赖于",
        "source_name": "RAG",
        "target_name": "LLM",
        "confidence": 0.85
      }
    ]
  }
}
```

---

### 5.6 POST /api/kg/edges

**描述：** 创建KG关系

**请求体：**
```json
{
  "source_id": 1,
  "target_id": 2,
  "relation": "依赖于",
  "confidence": 0.9
}
```

---

### 5.7 GET /api/kg/search

**描述：** KG混合检索

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| q | String | 搜索查询（必填） |
| mode | String | 检索模式（keyword/semantic/hybrid） |
| top_k | Int | 返回数量 |

**响应：**
```json
{
  "success": true,
  "data": {
    "entities": [
      {
        "id": 1,
        "name": "RAG",
        "type": "concept",
        "description": "...",
        "score": 0.92,
        "match_type": "semantic"  // keyword/semantic/graph
      }
    ],
    "relations": [
      {"source": "RAG", "relation": "使用", "target": "向量数据库"}
    ],
    "mode": "hybrid"
  }
}
```

---

## 6. 对话管理 API

### 6.1 GET /api/convs

**描述：** 获取对话列表

**响应：**
```json
{
  "success": true,
  "data": {
    "conversations": [
      {
        "id": 1,
        "title": "关于RAG的讨论",
        "message_count": 5,
        "created_at": "2024-01-15T10:00:00",
        "updated_at": "2024-01-15T11:30:00"
      }
    ]
  }
}
```

---

### 6.2 GET /api/convs/{conv_id}

**描述：** 获取对话详情（消息历史）

**响应：**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "title": "关于RAG的讨论",
    "messages": [
      {
        "role": "user",
        "content": "什么是RAG?",
        "timestamp": "2024-01-15T10:00:00"
      },
      {
        "role": "assistant",
        "content": "RAG是一种...",
        "timestamp": "2024-01-15T10:02:00",
        "sources": [{"name": "RAG", "type": "concept"}]
      }
    ]
  }
}
```

---

### 6.3 DELETE /api/convs/{conv_id}

**描述：** 删除对话

---

## 7. 系统设置 API

### 7.1 GET /api/settings

**描述：** 获取当前LLM设置

**响应：**
```json
{
  "success": true,
  "data": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "embedding_model": "text-embedding-3-small",
    "available_providers": ["openai", "anthropic", "deepseek", "dashscope"]
  }
}
```

---

### 7.2 PUT /api/settings

**描述：** 更新LLM设置

**请求体：**
```json
{
  "provider": "deepseek",
  "model": "deepseek-chat",
  "temperature": 0.5
}
```

---

## 8. 健康检查 API

### 8.1 GET /api/health

**描述：** 系统健康检查

**响应：**
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "database": "connected",
    "llm": "available",
    "web_search": "available",
    "version": "1.0.0"
  }
}
```

---

## 9. 错误码说明

| 错误码 | 说明 |
|------|------|
| `INVALID_REQUEST` | 请求参数错误 |
| `NOT_FOUND` | 资源不存在 |
| `DATABASE_ERROR` | 数据库操作失败 |
| `LLM_ERROR` | LLM调用失败 |
| `WEB_SEARCH_ERROR` | 联网搜索失败 |
| `EMBEDDING_ERROR` | 向量嵌入失败 |

---

## 10. API调用示例（前端）

```typescript
// api/client.ts

import axios from 'axios';

const API_BASE = 'http://localhost:8001';

// 对话
export async function chat(message: string, conversationId?: number) {
  const response = await axios.post(`${API_BASE}/api/chat`, {
    message,
    conversation_id: conversationId
  });
  return response.data;
}

// 联网搜索
export async function webSearch(query: string, save = true) {
  const response = await axios.post(`${API_BASE}/api/websearch`, {
    query,
    save_to_kg: save,
    save_to_docs: save
  });
  return response.data;
}

// 导入文档
export async function ingestDocument(title: string, content: string, tags?: string[]) {
  const response = await axios.post(`${API_BASE}/api/ingest`, {
    title,
    content,
    tags
  });
  return response.data;
}

// KG搜索
export async function kgSearch(query: string, mode = 'hybrid') {
  const response = await axios.get(`${API_BASE}/api/kg/search`, {
    params: { q: query, mode }
  });
  return response.data;
}
```

---

## 11. Postman 测试集合

可导入以下 JSON 到 Postman 进行测试：

```json
{
  "info": {
    "name": "KG-Agent API",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Chat",
      "item": [
        {
          "name": "Auto Route Chat",
          "request": {
            "method": "POST",
            "url": "{{base_url}}/api/chat",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {
              "mode": "raw",
              "raw": "{\"message\": \"什么是RAG?\"}"
            }
          }
        }
      ]
    },
    {
      "name": "WebSearch",
      "item": [
        {
          "name": "Search and Save",
          "request": {
            "method": "POST",
            "url": "{{base_url}}/api/websearch",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {
              "mode": "raw",
              "raw": "{\"query\": \"最新AI论文\"}"
            }
          }
        }
      ]
    }
  ],
  "variable": [
    {"key": "base_url", "value": "http://localhost:8001"}
  ]
}
```