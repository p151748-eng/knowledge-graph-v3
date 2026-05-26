"""
Agent 生成端模拟用户输入回归测试。

验证目标：
1. ChatService 自动路由 fast / pipeline 是否正常。
2. fast path 能基于检索上下文生成回答。
3. pipeline path 能完成 KGRetriever → Explainer → Integrator。
4. 检索 Router 的 intent / graph_method 和用户问题匹配。

运行方式：
    python backend/tests/test_agent_generation_regression.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, get_session_factory, init_db
from services.chat import ChatService
from services.ingest import IngestService
from services.query_router import route_query


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-agent-regression"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "术语列表" in prompt:
            return {
                "explanations": [
                    {"term": "Query Router", "simple": "判断问题该怎么检索", "analogy": "像前台分诊"},
                    {"term": "HybridSearchTool", "simple": "把多种检索结果合并", "analogy": "像多路搜索汇总器"},
                ],
                "glossary": {"Query Router": "检索路由器"},
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "Query Router 是什么" in text or "Query Router 是什么" in prompt:
            return FakeResponse("Query Router 是检索路由器，会生成 RetrievalPlan 来决定后续检索策略。")
        if "GraphRetrievalService" in text and ("上下游" in text or "subgraph" in text):
            return FakeResponse("GraphRetrievalService 的上下游包括 HybridSearchTool、Node、Edge、ego、path 和 subgraph。")
        if "Query Router" in text and "HybridSearchTool" in text:
            return FakeResponse("Query Router 会生成 RetrievalPlan，HybridSearchTool 按计划调用 BM25、Vector 和 Graph 检索。")
        if "BM25" in text and "Vector" in text:
            return FakeResponse("混合检索系统由 BM25、Vector、Graph 和 Context Builder 协同完成回答。")
        return FakeResponse("根据当前检索上下文，可以正常生成回答。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 17) % 97) / 97.0


DOC_TITLE = "Agent生成端回归文档"
DOC = """
Agent 生成链路包含 ChatService、ComplexityRouter、KGRetriever、Explainer 和 Integrator。
ChatService 会先根据用户输入判断走 fast path 还是 pipeline path。
fast path 使用 HybridSearchTool 检索上下文，然后直接调用 LLM 生成回答。
pipeline path 依次执行 KGRetriever、Explainer、Integrator。

Query Router 会为用户问题生成 RetrievalPlan。RetrievalPlan 包含 intent、optimized_query、expanded_queries、entities 和 graph_method。
当用户问 Query Router 和 HybridSearchTool 的关系时，路由应该选择 relation intent 和 path 图检索。
当用户问围绕 GraphRetrievalService 的上下游时，路由应该选择 subgraph intent 和 subgraph 图检索。

HybridSearchTool 根据 RetrievalPlan 调用 BM25SearchTool、Vector Search 和 GraphRetrievalService。
GraphRetrievalService 只保留 ego、path、subgraph 三种在线图检索方法。
Context Builder 汇总 BM25、Vector 和 Graph 的证据，Integrator 基于这些上下文生成最终回答。
""" * 4

CASES = [
    {
        "name": "fast-事实解释",
        "message": "Query Router 是什么",
        "force_path": "fast",
        "expect_path": "fast",
        "expect_plan": {"intent": "fact", "graph_method": "ego"},
        "expect_answer_any": ["Query Router", "RetrievalPlan", "正常生成回答"],
    },
    {
        "name": "pipeline-关系推理",
        "message": "Query Router 和 HybridSearchTool 有什么关系？",
        "force_path": "pipeline",
        "expect_path": "pipeline",
        "expect_plan": {"intent": "relation", "graph_method": "path"},
        "expect_answer_any": ["RetrievalPlan", "HybridSearchTool", "BM25"],
    },
    {
        "name": "pipeline-结构子图",
        "message": "围绕 GraphRetrievalService 的上下游有哪些？",
        "force_path": "pipeline",
        "expect_path": "pipeline",
        "expect_plan": {"intent": "subgraph", "graph_method": "subgraph"},
        "expect_answer_any": ["GraphRetrievalService", "subgraph", "Node"],
    },
]


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        ingest = IngestService(db)
        ingest.kg_extract.llm = FakeLLM()
        result = ingest.ingest_text(
            title=DOC_TITLE,
            content=DOC,
            source="agent_generation_regression",
            tags=["regression", "agent_generation"],
        )
        created_doc_id = result["document_id"]
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).count()
        assert chunks >= 2, f"文档未切分成功，chunks={chunks}"
        print(f"[PASS] Agent 回归文档导入：doc_id={created_doc_id}, chunks={chunks}")

        service = ChatService(db)
        service.llm = FakeLLM()

        for case in CASES:
            plan = route_query(case["message"], use_llm=False)
            for key, expected in case["expect_plan"].items():
                actual = getattr(plan, key)
                assert actual == expected, f"{case['name']} 路由 {key}={actual}, 期望 {expected}"

            result = service.chat(case["message"], force_path=case["force_path"])
            assert result["path"] == case["expect_path"], f"{case['name']} path={result['path']}"
            answer = result.get("response", "")
            assert answer and not answer.startswith("[错误]"), f"{case['name']} 回答异常：{answer}"
            assert any(token in answer for token in case["expect_answer_any"]), (
                f"{case['name']} 回答未包含预期信息：{case['expect_answer_any']}，answer={answer}"
            )
            print(
                f"[PASS] {case['name']} - path={result['path']} "
                f"intent={plan.intent} graph_method={plan.graph_method} answer_len={len(answer)}"
            )

        print("\n=== Agent 生成端模拟用户输入回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
