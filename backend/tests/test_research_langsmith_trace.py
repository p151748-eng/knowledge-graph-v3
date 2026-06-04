"""
带 LangSmith tracing 的 research 工作流链路测试。

运行方式：
    python backend/tests/test_research_langsmith_trace.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from observability.langsmith_tracing import traceable
from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


class TraceResponse:
    def __init__(self, content):
        self.content = content


class TraceResearchLLM:
    provider = "fake"
    model = "fake-research-langsmith-trace"
    temperature = 0.0

    @traceable(name="trace_research_llm.embed", run_type="embedding")
    def embed(self, texts):
        return [[0.1 + (i * 0.01) for i in range(16)] for _ in texts]

    @traceable(name="trace_research_llm.complete_json", run_type="llm")
    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "比较 Self-RAG、CRAG、GraphRAG 的差异并形成研究判断",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "Self-RAG CRAG GraphRAG", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "compare_methods", "query": "compare Self-RAG CRAG GraphRAG", "depends_on": ["t1"], "params": {}},
                    {"id": "t3", "type": "find_research_gap", "query": "RAG verification graph retrieval gap", "depends_on": ["t2"], "params": {}},
                    {"id": "t4", "type": "verify_claims", "query": "verify comparison claims", "depends_on": ["t3"], "params": {}},
                ],
            }
        return {}

    @traceable(name="trace_research_llm.complete", run_type="llm")
    def complete(self, prompt, system_prompt="", **kwargs):
        text = f"{system_prompt}\n{prompt}"
        if "研究分析助手" in text:
            return TraceResponse(
                "研究结论：Self-RAG 强调检索后的自我反思，CRAG 强调证据评估与纠错，"
                "GraphRAG 强调图结构召回。一个可行研究切入点是把证据校验、纠错检索和图谱召回结合到个人知识库研究助手中。"
            )
        return TraceResponse("研究链路测试回答。")


def fake_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {
        "context_text": "证据：Self-RAG 关注检索与自我反思；CRAG 关注证据评估和纠错；GraphRAG 关注图结构召回。",
        "merged": [
            {"id": 1, "chunk_id": 1, "title": "Self-RAG", "content": "Self-RAG 关注检索与自我反思", "result_type": "chunk", "chunk_type": "method"},
            {"id": 2, "chunk_id": 2, "title": "CRAG", "content": "CRAG 关注证据评估和纠错", "result_type": "chunk", "chunk_type": "method"},
            {"id": 3, "chunk_id": 3, "title": "GraphRAG", "content": "GraphRAG 关注图结构召回", "result_type": "chunk", "chunk_type": "method"},
        ],
        "bm25_hits": [],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": True},
    }


@traceable(name="research_question_full_chain", run_type="chain")
def run_question(service, message):
    return service.chat(message, force_path="research")


def main():
    service = ChatService(db=None)
    service.llm = TraceResearchLLM()
    service._save_conversation = lambda *args, **kwargs: None
    service._load_history = lambda conversation_id: []
    service._build_history_prompt = lambda conversation_id, message="": ""

    question = "比较 Self-RAG、CRAG、GraphRAG 的差异，并给出个人知识库研究助手的研究切入点。"
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        answer = run_question(service, question)

    assert answer["path"] == "research", answer
    assert answer["research_intent"] == "method_comparison", answer.get("research_intent")
    assert answer["research_actions"], "缺少 research_actions"
    assert answer["tool_graph"], "缺少 tool_graph"
    assert answer["citation_verification"], "缺少 citation_verification"
    assert any(action.get("tool_name") == "HybridSearchTool" for action in answer["research_actions"]), answer["research_actions"]
    assert any(action.get("tool_name") == "CitationVerifier" for action in answer["research_actions"]), answer["research_actions"]
    assert "Self-RAG" in answer["response"] and "GraphRAG" in answer["response"], answer["response"]

    print("=== LangSmith research 工作流链路测试通过 ===")
    print(f"question={question}")
    print(f"path={answer.get('path')}")
    print(f"research_intent={answer.get('research_intent')}")
    print(f"actions={[action.get('tool_name') for action in answer.get('research_actions', [])]}")
    print(f"citation_supported={answer.get('citation_verification', {}).get('supported')}")
    print(f"response={answer.get('response')}")


if __name__ == "__main__":
    main()
