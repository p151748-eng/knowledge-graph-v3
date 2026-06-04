import json
import sys
import traceback
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
    model = "fake-web-trigger"
    temperature = 0.0

    def embed(self, texts):
        return [[0.1 for _ in range(16)] for _ in texts]

    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "联网触发验证",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "latest Self-RAG 2026", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "summarize_evidence", "query": "summarize", "depends_on": ["t1"], "params": {}},
                    {"id": "t3", "type": "verify_claims", "query": "verify", "depends_on": ["t2"], "params": {}},
                ],
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = f"{system_prompt}\n{prompt}"
        if "研究分析助手" in text:
            return FakeResponse("研究回答：根据当前证据，Self-RAG 近年发展需要外部论文补证；如果外部证据不足，应明确说明证据不足。")
        return FakeResponse("测试回答")


def empty_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {"context_text": "", "merged": [], "bm25_hits": [], "semantic_hits": [], "graph_hits": [], "plan": {}}


def weak_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {
        "context_text": "本地只有 Self-RAG 2023 原始论文片段，没有 2025 或 2026 后续论文。",
        "merged": [
            {"id": 1, "chunk_id": 1, "title": "Self-RAG 2023", "content": "Self-RAG 2023 提出自我反思检索增强生成。", "result_type": "chunk", "chunk_type": "abstract"}
        ],
        "bm25_hits": [],
        "semantic_hits": [],
        "graph_hits": [],
        "plan": {"bm25": True, "vector": True, "graph": False},
    }


def fake_web_evidence(self, query, missing_aspects, max_results=6):
    return [
        {
            "id": "web-1",
            "title": "Recent Self-RAG Survey 2026",
            "snippet": "A 2026 survey discusses Self-RAG variants, corrective retrieval, and agentic RAG evaluation.",
            "url": "https://example.org/self-rag-survey-2026",
            "source": "web",
            "result_type": "web",
            "content": "A 2026 survey discusses Self-RAG variants, corrective retrieval, and agentic RAG evaluation.",
            "citation": "[1]",
        },
        {
            "id": "web-2",
            "title": "Agentic RAG Evaluation 2025",
            "snippet": "Recent work evaluates RAG agents with retrieval reflection and citation verification.",
            "url": "https://example.org/agentic-rag-2025",
            "source": "web",
            "result_type": "web",
            "content": "Recent work evaluates RAG agents with retrieval reflection and citation verification.",
            "citation": "[2]",
        },
    ]


def compact(result):
    actions = result.get("research_actions") or []
    return {
        "path": result.get("path"),
        "intent": result.get("research_intent"),
        "response": result.get("response"),
        "evidence_count": len(result.get("evidence_items") or []),
        "actions": [
            {
                "step": action.get("step"),
                "node": action.get("node"),
                "action": action.get("action"),
                "tool_name": action.get("tool_name"),
                "status": action.get("status"),
                "next_node": action.get("next_node"),
                "reason": action.get("reason"),
                "observation_summary": action.get("observation_summary"),
                "evidence_count": action.get("evidence_count"),
            }
            for action in actions
        ],
        "graph_nodes": [item.get("node") for item in result.get("graph_trace", [])],
        "citation_verification": result.get("citation_verification"),
    }


def make_service():
    service = ChatService(db=None)
    service.llm = FakeLLM()
    service._save_conversation = lambda *args, **kwargs: None
    service._load_history = lambda conversation_id: []
    service._build_history_prompt = lambda conversation_id, message="": ""
    return service


def main():
    output_path = ROOT / "tests" / "tmp_research_web_trigger_output.json"
    cases = []

    scenarios = [
        {
            "name": "explicit_web_latest",
            "question": "帮我综述 2023-2026 年 Self-RAG 的发展，重点联网找近年论文。",
            "retrieval": weak_retrieval,
        },
        {
            "name": "freshness_latest",
            "question": "这个方向最新还有哪些研究空白？",
            "retrieval": weak_retrieval,
        },
        {
            "name": "empty_local_with_web_request",
            "question": "联网搜索 Agentic RAG 2026 最新研究空白并给出研究方案。",
            "retrieval": empty_retrieval,
        },
    ]

    for scenario in scenarios:
        service = make_service()
        try:
            with patch.object(HybridSearchTool, "execute", scenario["retrieval"]), patch("agents.planned_workflow.ResearchWorkflow._search_web_evidence", fake_web_evidence):
                result = service.chat(scenario["question"], force_path="research")
                cases.append({"name": scenario["name"], "question": scenario["question"], **compact(result)})
        except Exception as exc:
            cases.append({"name": scenario["name"], "question": scenario["question"], "error": str(exc), "traceback": traceback.format_exc()})

    output_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in cases:
        web_actions = [a for a in case.get("actions", []) if a.get("action") == "search_academic_or_web"]
        print("=" * 80)
        print(case.get("name"))
        print("path=", case.get("path"), "intent=", case.get("intent"), "evidence=", case.get("evidence_count"))
        print("graph_nodes=", case.get("graph_nodes"))
        print("web_actions=", web_actions)
        print("supported=", (case.get("citation_verification") or {}).get("supported"))
    print(f"OUTPUT={output_path}")


if __name__ == "__main__":
    main()
