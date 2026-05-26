"""
带 LangSmith tracing 的论文问答完整链路测试。

运行方式：
    python backend/tests/test_paper_langsmith_trace.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import Document, get_session_factory, init_db
from services.chat import ChatService
from services.ingest import IngestService
from observability.langsmith_tracing import traceable


PAPER = """
# LangSmith Trace Paper TracePaperRAG2026

Alice Researcher
2026

## Abstract
TracePaperRAG2026 studies traceable paper assistant retrieval for full question-answer chains.

## Method
Method: TracePaperRAG
TracePaperRAG combines BM25 retrieval, vector retrieval, graph retrieval, evidence grading and expert agent answering.

## Experiments
Dataset: S2ORC, arXiv
Metric: F1, citation accuracy
TracePaperRAG is evaluated on scientific paper question answering and citation-grounded answers.

| Model | Dataset | Metric |
| --- | --- | --- |
| TracePaperRAG | S2ORC | F1 |
| TracePaperRAG | arXiv | citation accuracy |

## Related Work
Prior work includes retrieval augmented generation, Self-RAG and corrective RAG.

## References
[1] Lewis et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. 2020.
[2] Asai et al. Self-RAG: Learning to Retrieve, Generate, and Critique. 2023.
"""


class RealAnswerResponse:
    def __init__(self, content):
        self.content = content


class TraceFakeLLM:
    provider = "fake"
    model = "fake-langsmith-trace"
    temperature = 0.0

    @traceable(name="trace_fake_llm.embed", run_type="embedding")
    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    @traceable(name="trace_fake_llm.complete_json", run_type="llm")
    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            return {
                "relevance_score": 0.9,
                "support_score": 0.86,
                "coverage_score": 0.84,
                "freshness_required": False,
                "conflict_detected": False,
                "sufficient": True,
                "missing_aspects": [],
                "next_action": "answer",
                "reason": "LangSmith 链路测试证据覆盖充分",
            }
        return {}

    @traceable(name="trace_fake_llm.complete", run_type="llm")
    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "实验分析专家" in text:
            return RealAnswerResponse(
                "完整链路回答：TracePaperRAG 使用 S2ORC 和 arXiv 数据集，指标包括 F1 与 citation accuracy；"
                "链路经过 BM25、向量检索、图检索、证据评分和实验分析专家 Agent。"
            )
        return RealAnswerResponse("完整链路回答：TracePaperRAG 用于可追踪论文问答。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 31) % 101) / 101.0


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_langsmith_trace_regression").all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


@traceable(name="paper_question_full_chain", run_type="chain")
def run_question(service, message):
    return service.chat(message, force_path="paper_assistant")


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        cleanup_regression_docs(db)
        ingest = IngestService(db)
        ingest.kg_extract.llm = TraceFakeLLM()
        result = ingest.ingest_text(
            title="LangSmith Trace Paper TracePaperRAG2026",
            content=PAPER,
            source="paper_langsmith_trace_regression",
            tags=["paper", "langsmith_trace"],
        )
        created_doc_id = result["document_id"]

        service = ChatService(db)
        service.llm = TraceFakeLLM()
        question = "TracePaperRAG2026 实验用了哪些数据集和指标？"
        answer = run_question(service, question)

        assert answer["path"] == "paper_assistant", answer
        assert answer["paper_task"]["task_type"] == "experiment", answer["paper_task"]
        assert answer["paper_task"].get("expert") == "paper_experiment_expert", answer["paper_task"]
        assert "S2ORC" in answer["response"] and "F1" in answer["response"], answer["response"]
        assert answer["sources"], "缺少来源"
        assert answer["evidence_grade"].get("sufficient") is True, answer["evidence_grade"]
        assert answer["retrieval_rounds"], "缺少检索轮次"

        print("=== LangSmith 论文问答完整链路测试通过 ===")
        print(f"question={question}")
        print(f"answer={answer['response']}")
        print(f"task={answer['paper_task']}")
        print(f"evidence_grade={answer['evidence_grade']}")
        print(f"retrieval_rounds={answer['retrieval_rounds']}")
        print(f"sources_count={len(answer['sources'])}")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
