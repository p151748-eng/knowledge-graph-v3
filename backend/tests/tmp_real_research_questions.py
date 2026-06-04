import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-real-question"
    temperature = 0.0

    def embed(self, texts):
        return [[0.1 for _ in range(16)] for _ in texts]

    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "受控研究验证",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "Self-RAG CRAG GraphRAG research", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "compare_methods", "query": "compare", "depends_on": ["t1"], "params": {}},
                    {"id": "t3", "type": "generate_proposal", "query": "proposal", "depends_on": ["t2"], "params": {}},
                ],
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = f"{system_prompt}\n{prompt}"
        if "研究分析助手" in text:
            return FakeResponse("研究方案：Self-RAG 强调检索后的自我反思，CRAG 强调证据评估与修正，GraphRAG 强调图结构召回；可围绕个人知识库中的证据校验与图谱增强检索设计研究路线。")
        return FakeResponse("快速回答：RAG 是检索增强生成，用外部知识补充大模型回答。")


def fake_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {
        "context_text": "证据：Self-RAG 关注检索与反思；CRAG 关注证据评估和修正；GraphRAG 关注图结构召回。",
        "merged": [
            {"id": 1, "chunk_id": 1, "title": "Self-RAG", "content": "Self-RAG 关注检索与反思", "result_type": "chunk", "chunk_type": "method"},
            {"id": 2, "chunk_id": 2, "title": "CRAG", "content": "CRAG 关注证据评估和修正", "result_type": "chunk", "chunk_type": "method"},
            {"id": 3, "chunk_id": 3, "title": "GraphRAG", "content": "GraphRAG 关注图结构召回", "result_type": "chunk", "chunk_type": "method"},
        ],
        "bm25_hits": [],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": True},
    }


def make_service():
    svc = ChatService(db=None)
    svc.llm = FakeLLM()
    svc._save_conversation = lambda *args, **kwargs: None
    svc._load_history = lambda conversation_id: []
    svc._build_history_prompt = lambda conversation_id, message="": ""
    return svc


QUESTIONS = [
    ("RAG 是什么？", "fast", None),
    ("这篇论文的方法是什么？", "paper_assistant", None),
    ("这个结论可靠吗？", "self_rag", None),
    ("RAG + 多智能体有什么可做的研究点？", "research", "direction_exploration"),
    ("帮我综述 2023-2026 年 Self-RAG 的发展。", "research", "literature_review"),
    ("比较 Self-RAG、CRAG、GraphRAG 的差异。", "research", "method_comparison"),
    ("这个方向还有哪些研究空白？", "research", "gap_analysis"),
    ("帮我基于这个方向设计本科论文技术路线。", "research", "proposal_design"),
]


def summarize(result):
    actions = result.get("research_actions") or []
    return {
        "path": result.get("path"),
        "intent": result.get("research_intent"),
        "actions": [a.get("action") for a in actions],
        "nodes": [t.get("node") for t in result.get("graph_trace", [])],
        "supported": (result.get("citation_verification") or {}).get("supported"),
        "evidence_count": len(result.get("evidence_items") or []),
        "response_prefix": (result.get("response") or "")[:80],
    }


def main():
    with patch.object(HybridSearchTool, "execute", fake_retrieval):
        svc = make_service()
        for question, expected_path, expected_intent in QUESTIONS:
            result = svc.chat(question)
            summary = summarize(result)
            ok_path = summary["path"] == expected_path
            ok_intent = expected_intent is None or summary["intent"] == expected_intent
            print("=" * 80)
            print("Q:", question)
            print("EXPECTED:", {"path": expected_path, "intent": expected_intent})
            print("ACTUAL:", summary)
            print("PASS:", ok_path and ok_intent)


if __name__ == "__main__":
    main()
