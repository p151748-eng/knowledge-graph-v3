import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import get_session_factory, init_db
from services.chat import ChatService

QUESTIONS = [
    "比较 Self-RAG、CRAG、GraphRAG 的差异，并给出个人知识库研究助手的研究切入点。",
    "帮我基于多篇论文找研究空白并生成开题报告。",
    "帮我综述 2023-2026 年 Self-RAG 的发展，重点找近年论文。",
    "RAG + 多智能体有什么可做的研究点？",
    "这个方向最新还有哪些研究空白？",
]


def compact_action(action):
    return {
        "step": action.get("step"),
        "node": action.get("node"),
        "action": action.get("action"),
        "tool_name": action.get("tool_name"),
        "status": action.get("status"),
        "next_node": action.get("next_node"),
        "intent": action.get("intent"),
        "evidence_count": action.get("evidence_count"),
        "reason": action.get("reason"),
        "observation_summary": action.get("observation_summary"),
    }


def run_one(service, question):
    result = service.chat(question, force_path="research")
    actions = result.get("research_actions") or []
    return {
        "question": question,
        "path": result.get("path"),
        "research_intent": result.get("research_intent"),
        "processing_time": result.get("processing_time"),
        "confidence": result.get("confidence"),
        "response": result.get("response"),
        "research_plan_tasks": (result.get("research_plan") or {}).get("tasks"),
        "actions": [compact_action(action) for action in actions],
        "graph_trace": result.get("graph_trace"),
        "evidence_count": len(result.get("evidence_items") or []),
        "sources_count": len(result.get("sources") or []),
        "citation_verification": result.get("citation_verification"),
        "answer_verification": result.get("answer_verification"),
    }


def main():
    output_path = ROOT / "tests" / "tmp_research_real_questions_output.json"
    init_db()
    db = get_session_factory()()
    service = ChatService(db)
    results = []
    try:
        for question in QUESTIONS:
            print(f"RUNNING: {question}")
            try:
                result = run_one(service, question)
                results.append(result)
                print(f"DONE: path={result.get('path')} intent={result.get('research_intent')} evidence={result.get('evidence_count')} supported={(result.get('citation_verification') or {}).get('supported')}")
            except Exception as exc:
                results.append({
                    "question": question,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                })
                print(f"ERROR: {exc}")
    finally:
        db.close()
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output_path}")


if __name__ == "__main__":
    main()
