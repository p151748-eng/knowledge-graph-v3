"""
Self-RAG / CRAG 回归测试。

运行方式：
    python backend/tests/test_self_rag_crag.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.self_rag_pipeline import SelfRAGPipeline
from core.context import AgentContext, PipelineData
from models.schemas import EvidenceGradeData
from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-self-rag"
    temperature = 0.0

    def embed(self, texts):
        return [[float((len(text) + i) % 17) / 17.0 for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            if "本地证据足够" in prompt:
                return {
                    "relevance_score": 0.9,
                    "support_score": 0.9,
                    "coverage_score": 0.9,
                    "freshness_required": False,
                    "conflict_detected": False,
                    "sufficient": True,
                    "missing_aspects": [],
                    "next_action": "answer",
                    "reason": "本地证据足够",
                }
            if "最新" in prompt or "2026" in prompt:
                return {
                    "relevance_score": 0.3,
                    "support_score": 0.2,
                    "coverage_score": 0.2,
                    "freshness_required": True,
                    "conflict_detected": False,
                    "sufficient": False,
                    "missing_aspects": ["需要最新外部资料"],
                    "next_action": "web_verify",
                    "reason": "需要联网验证",
                }
            return {
                "relevance_score": 0.4,
                "support_score": 0.4,
                "coverage_score": 0.4,
                "freshness_required": False,
                "conflict_detected": False,
                "sufficient": False,
                "missing_aspects": ["缺少关系证据"],
                "next_action": "rewrite_local",
                "reason": "需要本地修正",
            }
        if "CRAG 检索修正器" in prompt:
            return {
                "rewritten_query": "本地证据足够 修正后问题",
                "expanded_queries": ["补充关系证据"],
                "strategy": {"bm25": True, "vector": True, "graph": True, "graph_method": "path", "bm25_top_k": 12, "vector_top_k": 12, "graph_top_k": 10},
                "reason": "改写并提高检索覆盖",
            }
        if "Web 证据评估器" in prompt:
            return {"accepted": [{"index": 0, "score": 0.9, "reason": "可补足最新资料"}]}
        if "答案支撑性校验器" in prompt:
            return {"supported": True, "support_score": 0.85, "unsupported_claims": [], "final_action": "answer", "reason": "答案有证据支撑"}
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        return FakeResponse("这是基于本地证据和必要联网证据生成的 Self-RAG 回答。")


def fake_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    enough = "本地证据足够" in query or (plan_override and plan_override.get("graph_method") == "path")
    return {
        "context_text": "本地证据足够：BM25、Vector、Graph 可以支撑回答。" if enough else "弱证据：只有零散片段。",
        "merged": [{"id": 1, "chunk_id": 1, "title": "测试文档", "content": "本地证据足够", "result_type": "chunk"}],
        "bm25_hits": [{"id": 1, "chunk_id": 1, "title": "测试文档", "content": "本地证据足够", "result_type": "chunk"}],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": bool(plan_override), "graph_method": (plan_override or {}).get("graph_method", "none")},
    }


def test_local_sufficient_no_web():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        pipeline = SelfRAGPipeline(db=None, llm=FakeLLM(), allow_web=True)
        context = AgentContext(pipeline_data=PipelineData(query="本地证据足够的问题"))
        result = pipeline.run(context)
        assert result.success
        assert len(context.pipeline_data.retrieval_attempts) == 1
        assert context.pipeline_data.web_evidence == []
        assert result.output["answer_verification"]["supported"] is True


def test_local_repair_success():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        pipeline = SelfRAGPipeline(db=None, llm=FakeLLM(), allow_web=False)
        context = AgentContext(pipeline_data=PipelineData(query="需要关系证据的问题"))
        result = pipeline.run(context)
        assert result.success
        assert len(context.pipeline_data.retrieval_attempts) == 2
        assert context.pipeline_data.retrieval_attempts[1].strategy["graph_method"] == "path"


def test_web_verify_accepts_real_and_rejects_simulated():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        pipeline = SelfRAGPipeline(db=None, llm=FakeLLM(), allow_web=True)
        with patch("agents.web_verifier.WebSearchTool.execute", return_value={
            "results": [
                {"title": "Self-RAG paper", "url": "https://arxiv.org/abs/2310.11511", "snippet": "Self-RAG retrieves and critiques evidence."},
                {"title": "[模拟] fake", "url": "https://example.com", "snippet": "模拟结果"},
            ]
        }):
            context = AgentContext(pipeline_data=PipelineData(query="Self-RAG 2026 最新资料"))
            result = pipeline.run(context)
            assert result.success
            assert len(context.pipeline_data.web_evidence) == 1
            assert context.pipeline_data.web_evidence[0]["url"] != "https://example.com"


def test_chat_service_self_rag_path():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        service = ChatService(db=None)
        service.llm = FakeLLM()
        service._save_conversation = lambda *args, **kwargs: None
        result = service.chat("本地证据足够的问题", force_path="self_rag")
        assert result["path"] == "self_rag"
        assert "retrieval_rounds" in result
        assert result["response"]


if __name__ == "__main__":
    test_local_sufficient_no_web()
    test_local_repair_success()
    test_web_verify_accepts_real_and_rejects_simulated()
    test_chat_service_self_rag_path()
    print("=== Self-RAG / CRAG 回归测试通过 ===")
