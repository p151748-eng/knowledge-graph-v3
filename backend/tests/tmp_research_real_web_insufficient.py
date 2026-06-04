import json
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import get_session_factory, init_db
from services.chat import ChatService
from tools.hybrid_search import HybridSearchTool


QUESTION = "Agentic RAG 在 2026 年还有哪些最新研究空白？请基于证据给出一个可做的研究问题。"


def empty_retrieval(self, query, top_k=10, context="", use_llm_router=True, plan_override=None):
    return {"context_text": "", "merged": [], "bm25_hits": [], "semantic_hits": [], "graph_hits": [], "plan": {}}


def compact_action(action):
    return {
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


def main():
    output_path = ROOT / "tests" / "tmp_research_real_web_insufficient_output.json"
    init_db()
    db = get_session_factory()()
    service = ChatService(db)
    try:
        with patch.object(HybridSearchTool, "execute", empty_retrieval):
            result = service.chat(QUESTION, force_path="research")
        output = {
            "question": QUESTION,
            "path": result.get("path"),
            "intent": result.get("research_intent"),
            "processing_time": result.get("processing_time"),
            "response": result.get("response"),
            "actions": [compact_action(action) for action in result.get("research_actions", [])],
            "graph_trace": result.get("graph_trace"),
            "evidence_items": result.get("evidence_items"),
            "sources": result.get("sources"),
            "citation_verification": result.get("citation_verification"),
            "answer_verification": result.get("answer_verification"),
        }
    except Exception as exc:
        output = {"question": QUESTION, "error": str(exc), "traceback": traceback.format_exc()}
    finally:
        db.close()
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output_path}")
    if "error" in output:
        print("ERROR", output["error"])
        return
    web_actions = [action for action in output["actions"] if action.get("action") == "search_academic_or_web"]
    print("path=", output["path"], "intent=", output["intent"], "time=", output["processing_time"])
    print("web_actions=", json.dumps(web_actions, ensure_ascii=False, indent=2))
    print("evidence_count=", len(output.get("evidence_items") or []))
    print("sources_count=", len(output.get("sources") or []))
    print("supported=", (output.get("citation_verification") or {}).get("supported"))
    print("support_score=", (output.get("citation_verification") or {}).get("support_score"))
    print("unsupported_claims=", (output.get("citation_verification") or {}).get("unsupported_claims"))
    print("response_prefix=", (output.get("response") or "")[:600])


if __name__ == "__main__":
    main()
