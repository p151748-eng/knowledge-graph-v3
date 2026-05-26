"""
使用真实 LLM 配置测试 LangSmith 论文问答完整链路。

运行方式：
    python backend/tests/test_paper_langsmith_real_answer.py
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
# LangSmith Live Paper LiveTraceRAG2026

Alice Researcher
2026

## Abstract
LiveTraceRAG2026 studies traceable paper assistant retrieval for complete question-answer chains.
It focuses on making each answer auditable through retrieval evidence, graph evidence, evidence grading and expert-agent generation.

## Introduction
Paper assistants for students need to explain methods and experiments while showing where each claim comes from.
The LiveTraceRAG2026 system combines local knowledge base retrieval and manager-agent orchestration.

## Method
Method: LiveTraceRAG
LiveTraceRAG uses BM25 retrieval for exact terms, vector retrieval for semantic evidence, and paper graph retrieval for structural evidence.
A manager agent routes the question to an experiment expert, method expert, comparison expert, literature review expert or writing expert.
EvidenceGrader checks whether the retrieved chunks support the answer before generation.

## Experiments
Dataset: S2ORC, arXiv HTML full text, AI paper notes
Metric: F1, evidence coverage, citation accuracy
LiveTraceRAG is evaluated on scientific paper question answering, experiment analysis and citation-grounded answers.
The experiment section reports that combining BM25, vector retrieval and paper graph retrieval improves evidence coverage for paper-reference questions.

| Model | Dataset | Metric | Result |
| --- | --- | --- | --- |
| LiveTraceRAG | S2ORC | F1 | 82.4 |
| LiveTraceRAG | arXiv HTML full text | citation accuracy | 88.1 |
| LiveTraceRAG | AI paper notes | evidence coverage | 91.3 |

## Related Work
Prior work includes retrieval augmented generation, Self-RAG, corrective RAG and graph-based retrieval.

## Conclusion
LiveTraceRAG concludes that a traceable manager-agent paper assistant can improve student-facing paper explanation by combining structured chunks, hybrid retrieval, evidence grading and expert answers.

## References
[1] Lewis et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. 2020.
[2] Asai et al. Self-RAG: Learning to Retrieve, Generate, and Critique. 2023.
"""


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_langsmith_real_answer_regression").all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


@traceable(name="real_paper_question_full_chain", run_type="chain")
def run_question(service, message):
    return service.chat(message, force_path="paper_assistant")


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        cleanup_regression_docs(db)
        ingest = IngestService(db)
        result = ingest.ingest_text(
            title="LangSmith Live Paper LiveTraceRAG2026",
            content=PAPER,
            source="paper_langsmith_real_answer_regression",
            tags=["paper", "langsmith_real_answer"],
        )
        created_doc_id = result["document_id"]

        service = ChatService(db)
        question = "LiveTraceRAG2026 的实验用了哪些数据集和指标？请结合证据完整回答。"
        answer = run_question(service, question)

        print("=== LangSmith 真实大模型论文问答完整链路测试完成 ===")
        print(f"question={question}")
        print(f"path={answer.get('path')}")
        print(f"response={answer.get('response')}")
        print(f"paper_task={answer.get('paper_task')}")
        print(f"evidence_grade={answer.get('evidence_grade')}")
        print(f"retrieval_rounds={answer.get('retrieval_rounds')}")
        print(f"sources_count={len(answer.get('sources') or [])}")
        for index, source in enumerate((answer.get("sources") or [])[:8], start=1):
            print(f"source_{index}={source}")

        assert answer.get("path") == "paper_assistant", answer
        assert answer.get("paper_task", {}).get("task_type") == "experiment", answer.get("paper_task")
        assert answer.get("response"), answer
        assert answer.get("sources"), "缺少来源"
        assert answer.get("evidence_grade", {}).get("sufficient") is True, answer.get("evidence_grade")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
