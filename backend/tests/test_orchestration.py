"""
Agent orchestration regression tests.

Run:
    python backend/tests/test_orchestration.py
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.planned_workflow import ExecutionPlan, PlannedTask, ResearchWorkflow
from core.context import AgentContext, PipelineData
from core.router import ContextAwareRouter, RouteInput
from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-orchestration"
    temperature = 0.0

    def embed(self, texts):
        return [[float((len(text) + i) % 11) / 11.0 for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "生成研究方案",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "Agentic RAG", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "compare_methods", "query": "Agentic RAG", "depends_on": ["t1"], "params": {}},
                ],
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = f"{system_prompt}\n{prompt}"
        if "研究分析助手" in text:
            return FakeResponse("研究方案：基于证据对比方法，并提出可验证的下一步方向。")
        return FakeResponse("这是编排测试回答。")


def fake_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {
        "context_text": "本地证据：Query Router、Self-RAG、论文方法和 GraphRAG 都有相关内容。",
        "merged": [
            {"id": 1, "chunk_id": 1, "title": "编排测试文档", "content": "本地证据", "result_type": "chunk", "chunk_type": "abstract"}
        ],
        "bm25_hits": [],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": False},
    }


def test_context_aware_router_paths():
    router = ContextAwareRouter()
    assert router.route(RouteInput(query="Query Router 是什么")).path == "fast"
    assert router.route(RouteInput(query="这篇论文的方法部分怎么做？")).path == "paper_assistant"
    assert router.route(RouteInput(query="这篇论文的主要贡献是什么？")).path == "paper_assistant"
    assert router.route(RouteInput(query="这篇论文的局限性是什么？")).path == "paper_assistant"
    assert router.route(RouteInput(query="这个结论可靠吗？需要验证依据")).path == "self_rag"
    assert router.route(RouteInput(query="现在 2026 年这个方法还是最新的吗？请查证")).path == "self_rag"
    assert router.route(RouteInput(query="Query Router 和 HybridSearchTool 有什么关系？")).path == "pipeline"
    assert router.route(RouteInput(query="帮我基于多篇论文找研究空白并生成开题报告")).path == "research"
    assert router.route(RouteInput(query="帮我比较 Self-RAG、CRAG、GraphRAG 的差异，并设计一个适合个人知识库的 KG-Agent 架构。" )).path == "research"
    assert router.route(RouteInput(query="如果我要把论文助手升级成能自动验证引用的研究助手，应该如何拆解技术路线？")).path == "research"


def test_context_followup_inherits_path():
    router = ContextAwareRouter()
    decision = router.route(RouteInput(
        query="那实验呢？",
        recent_turns=[{"role": "assistant", "content": "论文方法回答", "path": "paper_assistant", "intent": "paper_method"}],
    ))
    assert decision.path == "paper_assistant"
    assert decision.context_dependent is True
    assert decision.topic_changed is False
    assert decision.intent == "paper_experiment"


def test_planned_workflow_validation_adds_verify_claims():
    workflow = ResearchWorkflow(db=None, llm=FakeLLM())
    plan = ExecutionPlan(goal="研究方案", tasks=[PlannedTask(id="t1", type="retrieve_papers")])
    validated = workflow._validate_plan(plan)
    assert validated.tasks[-1].type == "verify_claims"


def test_planned_workflow_rejects_illegal_task():
    workflow = ResearchWorkflow(db=None, llm=FakeLLM())
    plan = ExecutionPlan(goal="研究方案", tasks=[PlannedTask(id="t1", type="delete_database")])
    try:
        workflow._validate_plan(plan)
    except ValueError as exc:
        assert "不允许" in str(exc)
    else:
        raise AssertionError("非法 task 未被拦截")


def test_chat_and_stream_auto_path_consistent():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        service = ChatService(db=None)
        service.llm = FakeLLM()
        service._save_conversation = lambda *args, **kwargs: None
        result = service.chat("Query Router 是什么")
        assert result["path"] == "fast"

        async def collect():
            events = []
            async for event in service.stream_chat("Query Router 是什么"):
                events.append(event)
            return events

        events = asyncio.run(collect())
        metrics = [event for event in events if event.get("type") == "metrics"][-1]
        assert metrics["path"] == result["path"]


def test_complex_research_question_uses_planned_workflow():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        service = ChatService(db=None)
        service.llm = FakeLLM()
        service._save_conversation = lambda *args, **kwargs: None
        result = service.chat("帮我基于多篇论文找研究空白并生成开题报告")
        assert result["path"] == "research"
        assert result["research_plan"]["tasks"][-1]["type"] == "verify_claims"
        assert "研究方案" in result["response"]


def test_forced_self_rag_complex_question_reports_evidence():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        service = ChatService(db=None)
        service.llm = FakeLLM()
        service._save_conversation = lambda *args, **kwargs: None
        result = service.chat("这个结论可靠吗？请验证依据", force_path="self_rag")
        assert result["path"] == "self_rag"
        assert "retrieval_rounds" in result
        assert "answer_verification" in result


def main():
    test_context_aware_router_paths()
    test_context_followup_inherits_path()
    test_planned_workflow_validation_adds_verify_claims()
    test_planned_workflow_rejects_illegal_task()
    test_chat_and_stream_auto_path_consistent()
    test_complex_research_question_uses_planned_workflow()
    test_forced_self_rag_complex_question_reports_evidence()
    print("=== Agent orchestration regression tests passed ===")


if __name__ == "__main__":
    main()
