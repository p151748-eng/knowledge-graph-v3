# 代码清理建议报告

生成时间：2026-05-28

---

## 一、后端清理建议

### 3. 可删除的死代码模块

| 文件 | 内容 | 说明 | 建议 |
|------|------|------|------|
| `backend/tools/registry.py` | `ToolRegistry` 类 | 工具注册机制从未被调用，所有 Agent 直接实例化工具 | **删除整个文件** |
| `backend/utils/helpers.py` | `extract_keywords`, `truncate_text` | 完全未被导入，`query_router.py` 有独立实现 | **删除整个文件** |
| `backend/core/agent.py:39-54` | `bind_tools()`, `use_tool()` 方法 | 工具绑定机制已废弃 | **删除方法** |
| `backend/tests/.langsmith_real_answer_output.txt` | 输出日志文件 | 163KB 测试输出，非代码 | **删除** |

---

### 4. 可删除的兼容类

| 文件 | 行号 | 内容 | 说明 | 建议 |
|------|------|------|------|------|
| `backend/core/router.py` | 285-290 | `ComplexityRouter` 类 | 兼容旧调用点，无实际调用 | **删除** |

---

### 2. 可删除的工具脚本

以下脚本为一次性开发/迁移工具，未被其他代码导入：

| 文件 | 用途 | 建议 |
|------|------|------|
| `backend/add_col.py` | 数据库列添加脚本 | **删除**（迁移已完成） |
| `backend/add_messages.py` | 消息表初始化脚本 | **删除**（迁移已完成） |
| `backend/crawl_ai_docs.py` | AI 文档爬取工具 | **保留**（开发可能用到）或移至 `scripts/` |
| `backend/inspect_db.py` | 数据库检查工具 | **保留**（开发可能用到）或移至 `scripts/` |
| `backend/migrate.py` | 数据库迁移脚本 | **保留**（部署可能用到）或移至 `scripts/` |
| `backend/test_qwen.py` | Qwen API 测试脚本 | **删除**（临时测试） |

建议：若保留开发工具，统一移至 `backend/scripts/` 目录并添加 `.gitignore` 规则。

---

### 3. 所有 Agent、Service、Tool 都在使用

经检查导入链，以下模块全部被引用：

| 类别 | 模块 | 状态 |
|------|------|------|
| **Agents** | 16 个 Agent 文件 | 全部使用 |
| **Services** | 11 个 Service 文件 | 全部使用 |
| **Tools** | 7 个 Tool 文件 | 全部使用 |
| **Core** | `state_graph.py` | 被 `planned_workflow.py` 使用 |

---

### 4. 测试文件检查

31 个测试文件全部测试当前功能，未发现测试已删除功能的废弃测试。

---

## 二、前端清理建议

### 1. 未使用的 API 函数

| 文件 | 函数 | 行号 | 说明 | 建议 |
|------|------|------|------|------|
| `frontend/src/api/client.ts` | `chat` | 24 | 非流式聊天，已被 `chatStream` 替代 | **删除** |
| `frontend/src/api/client.ts` | `chatPaper` | 29 | 论文聊天，已被 `chatStream({ chat_path: 'paper' })` 替代 | **删除** |
| `frontend/src/api/client.ts` | `updateKGNode` | 121 | 更新节点，KG 页面无编辑 UI | **保留**（后续可能添加） |
| `frontend/src/api/client.ts` | `getConversation` | 170 | 获取单个对话，仅用列表接口 | **删除** |

---

### 2. 未使用的 TypeScript 类型

| 文件 | 类型 | 行号 | 说明 | 建议 |
|------|------|------|------|------|
| `frontend/src/types/index.ts` | `PaperGraphNode` | 170 | 被 `PaperGraphData` 内部引用 | **保留**（类型组合需要） |
| `frontend/src/types/index.ts` | `PaperGraphEdge` | 179 | 被 `PaperGraphData` 内部引用 | **保留**（类型组合需要） |
| `frontend/src/types/index.ts` | `Conversation` | 49 | 仅 `client.ts` 引用，但接口未用 | **删除** |
| `frontend/src/types/index.ts` | `Message` | 19 | 仅 `client.ts` 引用，实际用 `any` | **保留**（类型安全改进） |

---

### 3. 未使用的 npm 依赖

| 包名 | 状态 | 建议 |
|------|------|------|
| `@tanstack/react-query` | **从未导入** | **删除**（从 package.json 移除） |
| `highlight.js` | 仅 CSS 导入，JS 部分未用 | **保留 CSS**，可考虑替代方案 |

---

## 三、清理优先级

### 高优先级（推荐立即清理）

1. **删除 `ComplexityRouter`**（后端兼容类）
2. **删除未使用 API 函数**：`chat`、`chatPaper`、`getConversation`
3. **删除未使用 npm 包**：`@tanstack/react-query`
4. **删除临时测试脚本**：`test_qwen.py`、`add_col.py`、`add_messages.py`

### 中优先级（可选清理）

5. **整理开发工具脚本**：移至 `backend/scripts/` 目录
6. **删除未使用类型**：`Conversation`

### 低优先级（保留）

7. `updateKGNode`（后续可能添加编辑 UI）
8. `PaperGraphNode`、`PaperGraphEdge`（类型组合需要）
9. `Message` 类型（建议改用类型安全而非 `any`）
10. `highlight.js` CSS（语法高亮需要）

---

## 四、清理后代码量预估

| 类别 | 预计减少 |
|------|----------|
| 后端 Python 文件 | 3 个小文件 + 约 50 行 |
| 后端临时脚本 | 3 个文件 |
| 前端 TypeScript | 约 30 行 |
| npm 依赖 | 1 包 |
| 测试输出文件 | 1 个（163KB） |

---

## 五、执行建议

建议按以下步骤执行：

1. 创建清理分支：`git checkout -b cleanup-unused-code`
2. 按优先级逐一删除
3. 运行测试确认无破坏性影响：
   ```bash
   PYTHONPATH=backend python backend/tests/test_self_rag_crag.py
   PYTHONPATH=backend python backend/tests/test_paper_assistant_agent.py
   ```
4. 提交并合并

---

## 六、清理脚本（可选）

如需批量删除，可执行：

```bash
# 删除后端兼容类（需手动编辑 router.py）
# 删除后端临时脚本
rm backend/add_col.py backend/add_messages.py backend/test_qwen.py

# 删除前端未用函数和类型（需手动编辑）
# 删除 npm 依赖
cd frontend && npm uninstall @tanstack/react-query
```