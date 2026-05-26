"""
Fast bounded acceptance tests for agent orchestration.

Run:
    python backend/tests/test_orchestration_acceptance.py
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.paper_assistant import PaperAssistantAgent
from agents.planned_workflow import ExecutionPlan, PlannedTask, ResearchWorkflow
from agents.self_rag_pipeline import SelfRAGPipeline
from core.agent import AgentResult
from core.context import AgentContext, PipelineData
from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-acceptance"
    temperature = 0.0

    def embed(self, texts):
        return [[0.1 for _ in range(16)] for _ in texts]

    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "Agentic RAG 研究方案",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "Agentic RAG Self-RAG GraphRAG", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "compare_methods", "query": "compare", "depends_on": ["t1"], "params": {}},
                    {"id": "t3", "type": "generate_proposal", "query": "proposal", "depends_on": ["t2"], "params": {}},
                ],
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = f"{system_prompt}\n{prompt}"
        if "研究分析助手" in text:
            return FakeResponse("研究方案：先对比 Self-RAG、GraphRAG 和 CRAG，再提出带证据校验的个人知识库方向。")
        return FakeResponse("快速回答：Query Router 用于判断问题该走哪个检索和回答路径。")


def fake_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {
        "context_text": "证据：Self-RAG 关注检索与自我反思，GraphRAG 关注图结构召回，CRAG 关注证据评估和修正。",
        "merged": [
            {"id": 1, "chunk_id": 1, "title": "Self-RAG", "content": "Self-RAG 关注检索与反思", "result_type": "chunk", "chunk_type": "method"},
            {"id": 2, "chunk_id": 2, "title": "GraphRAG", "content": "GraphRAG 关注图结构召回", "result_type": "chunk", "chunk_type": "method"},
        ],
        "bm25_hits": [],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": True},
    }


def fake_paper_run(self, context):
    return AgentResult(
        success=True,
        output={
            "answer": "论文助手回答：该论文方法使用 self-attention，实验使用 BLEU 指标。",
            "sources": [{"id": 1, "name": "paper chunk", "type": "chunk", "chunk_type": "method"}],
            "confidence": 0.82,
            "paper_task": {"task_type": "method", "expert": "paper_method_expert"},
            "retrieval_rounds": [{"round": 1}],
            "evidence_grade": {"sufficient": True},
        },
        confidence=0.82,
    )


def fake_self_rag_run(self, context):
    context.pipeline_data.retrieval_attempts = []
    return AgentResult(
        success=True,
        output={
            "answer": "Self-RAG 回答：当前结论有本地证据支撑，可靠性中高。",
            "sources": [{"id": 1, "name": "local evidence", "type": "document"}],
            "confidence": 0.78,
            "retrieval_rounds": [{"round": 1, "source": "local"}],
            "evidence_grade": {"sufficient": True, "coverage_score": 0.78},
            "answer_verification": {"supported": True, "support_score": 0.78},
            "web_sources": [],
        },
        confidence=0.78,
    )


def service():
    svc = ChatService(db=None)
    svc.llm = FakeLLM()
    svc._save_conversation = lambda *args, **kwargs: None
    svc._load_history = lambda conversation_id: []
    svc._build_history_prompt = lambda conversation_id, message="": ""
    return svc


def test_fast_path_is_low_overhead():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        result = service().chat("Query Router 是什么")
        assert result["path"] == "fast"
        assert "快速回答" in result["response"]
        assert result["confidence"] >= 0.7
        assert result["evidence_items"]
        assert "citation_verification" in result


def test_paper_path_reports_task_metadata():
    with patch.object(PaperAssistantAgent, "run", fake_paper_run):
        result = service().chat("这篇论文的方法部分怎么做？")
        assert result["path"] == "paper_assistant"
        assert result["paper_task"]["task_type"] == "method"
        assert result["sources"][0]["chunk_type"] == "method"
        assert "citation_verification" in result


def test_self_rag_path_reports_evidence_chain():
    with patch.object(SelfRAGPipeline, "run", fake_self_rag_run):
        result = service().chat("这个结论可靠吗？请验证依据")
        assert result["path"] == "self_rag"
        assert result["evidence_grade"]["sufficient"] is True
        assert result["answer_verification"]["supported"] is True
        assert result["retrieval_rounds"]
        assert "citation_verification" in result


def test_research_path_plans_and_verifies():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        result = service().chat("帮我基于多篇论文找研究空白并生成开题报告")
        assert result["path"] == "research"
        assert result["research_plan"]["tasks"][-1]["type"] == "verify_claims"
        assert result["answer_verification"]["supported"] is True
        assert result["citation_verification"]["supported"] is True
        assert result["evidence_items"]
        assert [item["node"] for item in result["graph_trace"]] == ["planner", "retrieval", "synthesis", "citation_verifier", "finalize"]
        assert "研究方案" in result["response"]


def test_design_and_technical_route_questions_use_research():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        svc = service()
        architecture = svc.chat("帮我比较 Self-RAG、CRAG、GraphRAG 的差异，并设计一个适合个人知识库的 KG-Agent 架构。")
        technical_route = svc.chat("如果我要把论文助手升级成能自动验证引用的研究助手，应该如何拆解技术路线？")
        assert architecture["path"] == "research"
        assert technical_route["path"] == "research"
        assert architecture["research_plan"]["tasks"][-1]["type"] == "verify_claims"
        assert technical_route["research_plan"]["tasks"][-1]["type"] == "verify_claims"


def test_context_followup_routes_to_previous_path():
    svc = service()
    svc._load_history = lambda conversation_id: [
        {"role": "assistant", "content": "论文方法回答", "path": "paper_assistant", "intent": "paper_method"}
    ]
    with patch.object(PaperAssistantAgent, "run", fake_paper_run):
        result = svc.chat("那实验呢？", conversation_id=1)
        assert result["path"] == "paper_assistant"


def test_stream_matches_chat_path_for_complex_research():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        svc = service()
        chat_result = svc.chat("帮我基于多篇论文找研究空白并生成开题报告")

        async def collect():
            events = []
            async for event in svc.stream_chat("帮我基于多篇论文找研究空白并生成开题报告"):
                events.append(event)
            return events

        events = asyncio.run(collect())
        metrics = [event for event in events if event.get("type") == "metrics"][-1]
        assert metrics["path"] == chat_result["path"] == "research"


def test_planned_workflow_rejects_bad_plan():
    workflow = ResearchWorkflow(db=None, llm=FakeLLM())
    bad_plan = ExecutionPlan(goal="bad", tasks=[PlannedTask(id="t1", type="send_email")])
    try:
        workflow._validate_plan(bad_plan)
    except ValueError as exc:
        assert "不允许" in str(exc)
    else:
        raise AssertionError("Bad planned task was accepted")


def test_research_without_evidence_is_not_supported():
    def empty_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
        return {"context_text": "", "merged": [], "bm25_hits": [], "semantic_hits": [], "graph_hits": [], "plan": {}}

    with patch.object(HybridSearchTool, "execute", empty_retrieval):
        result = service().chat("帮我基于多篇论文找研究空白并生成开题报告")
        assert result["path"] == "research"
        assert result["citation_verification"]["supported"] is False


def main():
    test_fast_path_is_low_overhead()
    test_paper_path_reports_task_metadata()
    test_self_rag_path_reports_evidence_chain()
    test_research_path_plans_and_verifies()
    test_design_and_technical_route_questions_use_research()
    test_context_followup_routes_to_previous_path()
    test_stream_matches_chat_path_for_complex_research()
    test_planned_workflow_rejects_bad_plan()
    test_research_without_evidence_is_not_supported()
    print("=== Fast orchestration acceptance tests passed ===")


if __name__ == "__main__":
    main()
