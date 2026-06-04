import json
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
    model = "fake-insufficient-web"
    temperature = 0.0

    def embed(self, texts):
        return [[0.1 for _ in range(16)] for _ in texts]

    def complete_json(self, prompt, json_schema):
        if "研究型知识库任务规划器" in prompt:
            return {
                "goal": "研究空白分析",
                "tasks": [
                    {"id": "t1", "type": "retrieve_papers", "query": "rare topic", "depends_on": [], "params": {}},
                    {"id": "t2", "type": "find_research_gap", "query": "rare topic gap", "depends_on": ["t1"], "params": {}},
                    {"id": "t3", "type": "verify_claims", "query": "verify", "depends_on": ["t2"], "params": {}},
                ],
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        if "研究分析助手" in f"{system_prompt}\n{prompt}":
            return FakeResponse("研究空白：本地证据不足，已使用外部证据补充后形成谨慎判断。")
        return FakeResponse("测试回答")


def empty_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {"context_text": "", "merged": [], "bm25_hits": [], "semantic_hits": [], "graph_hits": [], "plan": {}}


def fake_web_evidence(self, query, missing_aspects, max_results=6):
    return [
        {"id": "web-implicit-1", "title": "Rare Topic Research Gap", "content": "External evidence about rare topic research gaps.", "snippet": "External evidence about rare topic research gaps.", "url": "https://example.org/rare-topic-gap", "result_type": "web", "source": "web"}
    ]


def main():
    service = ChatService(db=None)
    service.llm = FakeLLM()
    service._save_conversation = lambda *args, **kwargs: None
    service._load_history = lambda conversation_id: []
    service._build_history_prompt = lambda conversation_id, message="": ""

    question = "这个冷门方向还有哪些研究空白？"
    with patch.object(HybridSearchTool, "execute", empty_retrieval), patch("agents.planned_workflow.ResearchWorkflow._search_web_evidence", fake_web_evidence):
        result = service.chat(question, force_path="research")

    actions = result.get("research_actions") or []
    web_actions = [action for action in actions if action.get("action") == "search_academic_or_web"]
    assert result.get("path") == "research", result
    assert result.get("research_intent") == "gap_analysis", result.get("research_intent")
    assert web_actions, actions
    assert web_actions[0].get("status") == "completed", web_actions
    assert web_actions[0].get("reason") == "本地证据不足，需要外部补证", web_actions
    assert len(result.get("evidence_items") or []) == 1, result.get("evidence_items")

    output = {
        "path": result.get("path"),
        "intent": result.get("research_intent"),
        "graph_nodes": [item.get("node") for item in result.get("graph_trace", [])],
        "web_actions": web_actions,
        "evidence_count": len(result.get("evidence_items") or []),
        "citation_verification": result.get("citation_verification"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
