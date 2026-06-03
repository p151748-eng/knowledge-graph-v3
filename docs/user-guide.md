# KG-Agent 操作手册

本文面向使用者，说明如何启动 KG-Agent、完成论文导入、进行论文问答、联网补充证据并查看知识图谱。

## 1. 启动前准备

### 1.1 基础环境

请先准备：

- Python 3.10+
- Node.js 18+
- MySQL 8.0+
- 至少一个可用 LLM API Key

### 1.2 安装依赖

后端：

```bash
pip install -r backend/requirements.txt
```

前端：

```bash
cd frontend
npm install
```

### 1.3 配置后端环境变量

复制模板：

```bash
cp backend/.env.example backend/.env
```

至少配置：

```env
DATABASE_URL=mysql+pymysql://root:your-password@localhost:3306/konw
LLM_PROVIDER=dashscope
LLM_MODEL=qwen-plus
QWEN_API_KEY=your-qwen-key
```

如需联网搜索与论文检索，请继续配置：

```env
BOCHA_SEARCH_ENABLED=true
BOCHA_API_KEY=your-bocha-api-key
WEB_SEARCH_MAX_RESULTS=5
```

不要把真实 `.env`、数据库密码或 API Key 提交到 Git。

### 1.4 创建数据库

```sql
CREATE DATABASE konw CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

如果你的 `.env` 使用其他数据库名，请以 `.env` 中的 `DATABASE_URL` 为准。

## 2. 启动系统

启动后端：

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

启动前端：

```bash
cd frontend
npm run dev
```

打开前端：

```text
http://localhost:5173
```

如果使用 [run.sh](../run.sh) 或 [run.bat](../run.bat)，注意脚本当前默认后端端口是 `8003`。

## 3. 页面导航

| 页面 | 路径 | 主要用途 |
| --- | --- | --- |
| 聊天 | `/` | 问答、论文助手、自校验检索、研究规划、查看来源和执行过程。 |
| 知识导入 | `/import` | 导入手动文本、文件或 arXiv 论文。 |
| 文档库 | `/docs` | 查看已导入文档、文档详情、分片和关联图谱。 |
| 知识图谱 | `/kg` | 搜索节点、管理节点/边、查看图谱可视化。 |
| 设置 | `/settings` | 配置 LLM 提供商、模型和温度参数。 |

## 4. 典型任务

### 4.1 导入一篇论文

1. 打开“知识导入”。
2. 选择 arXiv 导入或文件导入。
3. 输入 arXiv ID / URL，或上传 PDF / 文本文件。
4. 等待系统完成文档存储、分片、向量化和知识图谱抽取。
5. 到“文档库”确认论文已经出现。

### 4.2 使用 Paper Assistant 阅读论文

在“聊天”页面选择“论文助手”，或直接输入论文相关问题让系统自动路由。

示例：

```text
请概括这篇论文的研究问题、核心方法和主要贡献。
```

```text
这篇论文的方法部分有什么创新？和传统 RAG 有什么区别？
```

```text
请提取实验设置、对比方法、评价指标和主要结论。
```

期望结果：

- 回答结构更偏论文阅读。
- 来源中包含论文片段、章节或外部论文证据。
- 如果证据不足，系统会提示需要补充联网内容或更多上下文。

### 4.3 分析研究空白和创新点

示例：

```text
我想研究“多智能体 RAG 在医学论文阅读中的应用”，帮我分析这个选题的研究空白和创新点。
```

系统通常会进入论文助手或研究工作流，结合当前知识库和记忆上下文生成：

- 研究背景。
- 已有工作概括。
- 可能研究空白。
- 可设计的创新点。
- 风险与验证建议。

### 4.4 联网搜索最新论文并查看引用

在上一轮研究选题之后继续输入：

```text
帮我联网搜索这个选题的相关论文，重点找 2024 年以后的最新研究。
```

系统会识别“这个选题”为上下文追问，使用上一轮主题生成学术检索 query，并优先调用学术论文搜索。

期望结果：

- 回答中出现 `[1]`、`[2]` 等引用标记。
- 末尾出现“参考论文”“引用来源”或“引用链接”。
- 来源里包含标题、作者、年份、URL、provider 等字段。

如果没有出现引用链接，可以检查：

- 是否配置了联网搜索和学术检索相关 API Key。
- 当前问题是否明确要求“论文”“文献”“相关工作”“研究现状”或“联网搜索”。
- 返回结果是否确实包含 URL。

### 4.5 使用 Self-RAG 验证可靠性

示例：

```text
请验证 Self-RAG 机制在论文问答中是否可靠，并补充论文和官网依据。
```

期望结果：

- 系统先进行本地检索和证据评分。
- 如果证据不足，会进入联网验证。
- 论文证据优先来自学术搜索，官网/报告/GitHub 证据优先来自 Web Search。
- 回答中说明证据支撑程度和不确定性。

### 4.6 查看知识图谱

1. 打开“知识图谱”。
2. 在搜索框输入概念、论文标题、方法名或关键词。
3. 查看搜索结果和图谱结果。
4. 切换到图谱视图，观察节点和关系。
5. 可手动新增、编辑或删除节点与边。

适合查看：

- 某篇论文关联了哪些方法、指标、实验和数据集。
- 某个研究主题下有哪些概念和关系。
- 文档导入后抽取出的实体质量。

## 5. API 快速调用

健康检查：

```bash
curl http://localhost:8001/api/health
```

普通对话：

```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"什么是 RAG？"}'
```

强制论文助手：

```bash
curl -X POST http://localhost:8001/api/chat/paper \
  -H "Content-Type: application/json" \
  -d '{"message":"帮我分析多智能体 RAG 在医学论文阅读中的研究空白"}'
```

学术搜索：

```bash
curl -X POST http://localhost:8001/api/academic-search \
  -H "Content-Type: application/json" \
  -d '{"query":"multi-agent RAG medical literature review 2024", "max_results":5}'
```

更多接口见 [API.md](../API.md)。

## 6. 常见问题

### 前端能打开，但对话失败

检查：

- 后端是否启动。
- 前端 API 地址是否指向正确端口。
- 后端日志是否有数据库连接失败或 API Key 错误。

### 后端端口冲突

换一个端口启动：

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

同时确认前端 API 配置与后端端口一致。

### 联网搜索无结果

检查：

- `BOCHA_SEARCH_ENABLED` 是否为 `true`。
- `BOCHA_API_KEY` 是否有效。
- 网络环境是否允许访问外部搜索服务。
- 查询是否过长，可改成更短的英文关键词或明确主题。

### 论文引用不规范或没有链接

建议：

- 明确使用“联网搜索相关论文”“参考文献”“研究现状”“2024 年以后”等表达。
- 避免一次输入过多无关约束。
- 在第一轮先明确主题，第二轮再说“帮我联网搜索这个选题的相关论文”。

### 文档导入后图谱为空

可能原因：

- 文档内容太短或实体不明显。
- LLM API Key 不可用，导致实体关系抽取失败。
- 数据库写入失败。

可先在“文档库”确认文档已导入，再查看后端日志。
