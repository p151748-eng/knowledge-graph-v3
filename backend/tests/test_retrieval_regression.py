"""
复杂文档检索回归测试。

验证目标：
1. 复杂长文档导入后会生成 DocumentChunk。
2. BM25 能命中关键词型问题。
3. Vector 能命中语义解释型问题。
4. Graph 能按 query intent 选择 ego/path/subgraph。
5. HybridSearchTool 返回的 context_text 包含正确证据。

运行方式：
    python backend/tests/test_retrieval_regression.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, get_session_factory, init_db
from services.ingest import IngestService
from services.query_router import route_query
from tools.hybrid_search import HybridSearchTool


COMPLEX_DOC_TITLE = "回归测试-混合检索架构复杂文档"
COMPLEX_DOC = """
混合检索系统由 Query Router、BM25SearchTool、Vector Search、GraphRetrievalService、Context Builder 和 Answer Agent 组成。
Query Router 负责识别用户意图，并把问题改写成 optimized_query。对于“X 是什么”这类事实问题，它选择 ego 图检索；
对于“A 和 B 有什么关系”这类关系问题，它选择 path 多跳路径检索；对于“围绕 X 的上下游有哪些”这类结构问题，它选择 subgraph 主题子图检索。

BM25SearchTool 负责精确关键词召回。它适合检索 HybridSearchTool、RRF、DocumentChunk、graph_method 这类代码标识和术语。
Vector Search 负责语义召回。用户问“为什么要先理解问题再检索”时，向量检索应该找到 Query Router 和 query optimization 相关内容。
GraphRetrievalService 负责图上关系检索，只保留三种在线方法：ego、path、subgraph。
ego 用于解释单个实体周围的一跳邻居；path 用于查找两个实体之间的多跳链路；subgraph 用于围绕主题收集局部结构。

系统中存在如下关系：Query Router 生成 RetrievalPlan；RetrievalPlan 控制 HybridSearchTool；HybridSearchTool 调用 BM25SearchTool；
HybridSearchTool 调用 Vector Search；HybridSearchTool 调用 GraphRetrievalService；GraphRetrievalService 使用 Node 和 Edge 查询知识图谱；
Context Builder 汇总 BM25、Vector 和 Graph 的证据；Answer Agent 基于 Context Builder 生成最终回答。

为了避免图检索过慢，path 默认限制 2-hop，最多 3-hop；subgraph 限制节点和边数量；global_summary 第一版不跑在线 community 检索。
社区检索适合离线聚类和全局摘要，不适合作为第一版实时问答主链路。主题子图检索更适合实时回答模块上下游、局部架构和优化建议。
""" * 5

CASES = [
    {
        "name": "关键词-BM25-代码标识",
        "query": "HybridSearchTool 和 RetrievalPlan 怎么配合？",
        "expect_plan": {"bm25": True},
        "expect_any": ["HybridSearchTool", "RetrievalPlan"],
    },
    {
        "name": "语义-Query优化",
        "query": "为什么需要先理解 Query Router 再决定 Vector Search 检索策略？",
        "expect_plan": {"vector": True},
        "expect_any": ["Query Router", "optimized_query", "用户意图"],
    },
    {
        "name": "关系-Path图检索",
        "query": "Query Router 和 HybridSearchTool 有什么关系？",
        "expect_plan": {"graph": True, "graph_method": "path"},
        "expect_any": ["Query Router", "HybridSearchTool", "RetrievalPlan"],
    },
    {
        "name": "结构-Subgraph图检索",
        "query": "围绕 GraphRetrievalService 的上下游有哪些？",
        "expect_plan": {"graph": True, "graph_method": "subgraph"},
        "expect_any": ["GraphRetrievalService", "ego", "path", "subgraph"],
    },
    {
        "name": "全局-不跑在线图扩展",
        "query": "整体总结一下混合检索系统架构",
        "expect_plan": {"graph_method": "none"},
        "expect_any": ["混合检索", "BM25", "Vector", "Graph"],
    },
]


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        ingest = IngestService(db)
        result = ingest.ingest_text(
            title=COMPLEX_DOC_TITLE,
            content=COMPLEX_DOC,
            source="retrieval_regression",
            tags=["regression", "hybrid_search"],
        )
        created_doc_id = result["document_id"]
        chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).count()
        assert chunk_count >= 2, f"复杂文档未正确切分，chunk_count={chunk_count}"
        print(f"[PASS] 复杂文档导入并切分：doc_id={created_doc_id}, chunks={chunk_count}")

        search = HybridSearchTool(db)
        for case in CASES:
            plan = route_query(case["query"], use_llm=False)
            for key, expected in case["expect_plan"].items():
                actual = getattr(plan, key)
                assert actual == expected, f"{case['name']} 路由字段 {key}={actual}, 期望 {expected}"

            retrieval = search.execute(case["query"], top_k=8, use_llm_router=False)
            context_text = retrieval.get("context_text", "")
            merged = retrieval.get("merged", [])
            assert merged, f"{case['name']} 没有检索结果"
            assert any(token in context_text for token in case["expect_any"]), (
                f"{case['name']} context 未命中预期证据：{case['expect_any']}"
            )
            print(
                f"[PASS] {case['name']} - intent={retrieval['plan']['intent']} "
                f"graph_method={retrieval['plan']['graph_method']} results={len(merged)}"
            )

        print("\n=== 复杂文档检索回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
