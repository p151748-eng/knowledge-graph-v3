"""
论文助手 Self-RAG / CRAG 接入回归测试。

验证目标：
1. 论文任务会输出 evidence_grade 与 retrieval_rounds。
2. 证据缺少任务必需 chunk_type 时会触发本地检索修复。
3. 证据足够时不会无意义多轮重试。

运行方式：
    python backend/tests/test_paper_self_rag.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import Document, DocumentChunk, get_session_factory, init_db
from services.chat import ChatService
from services.ingest import IngestService


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-paper-self-rag"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            return {
                "relevance_score": 0.8,
                "support_score": 0.76,
                "coverage_score": 0.74,
                "freshness_required": False,
                "conflict_detected": False,
                "sufficient": True,
                "missing_aspects": [],
                "next_action": "answer",
                "reason": "检索证据相关",
            }
        if "CRAG 检索修正器" in prompt:
            return {
                "rewritten_query": "ZypherNoExpAlpha42 experiment dataset metric table",
                "expanded_queries": ["experiment dataset metric", "table results"],
                "strategy": {
                    "bm25": True,
                    "vector": True,
                    "graph": False,
                    "graph_method": "none",
                    "bm25_top_k": 14,
                    "vector_top_k": 14,
                    "graph_top_k": 8,
                },
                "reason": "补充实验证据检索词",
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "【回答风格】\nexperiment_analysis" in text:
            return FakeResponse("实验分析：当前证据显示模型使用 WMT 2014 和 BLEU；如果缺少实验 chunk，应谨慎说明证据不足。")
        return FakeResponse("论文回答：基于摘要、方法和实验等论文证据生成。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 17) % 101) / 101.0


SUFFICIENT_PAPER = """
# Retrieval Paper

Alice Researcher
2024

## Abstract
This paper studies retrieval augmented generation for scientific question answering.

## Method
Method: HybridRAG
The method combines BM25, vector retrieval, and paper graph retrieval.

## Experiments
Dataset: WMT 2014, Natural Questions
The main metrics are BLEU and F1.

| Model | Dataset | Metric |
| --- | --- | --- |
| HybridRAG | WMT 2014 | BLEU |

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


INSUFFICIENT_PAPER = """
# Retrieval Paper Without Experiments

Alice Researcher
2024

## Abstract
A controlled study about ZypherNoExpAlpha42 retrieval without reported experiment tables.

## Method
Method: ZypherNoExpAlpha42
The method combines BM25 and vector retrieval.

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


def ingest_paper(db, content, title):
    ingest = IngestService(db)
    ingest.kg_extract.llm = FakeLLM()
    result = ingest.ingest_text(title=title, content=content, source="paper_self_rag_regression", tags=["paper", "self_rag"])
    return result["document_id"]


def run_paper_chat(db, message):
    service = ChatService(db)
    service.llm = FakeLLM()
    return service.chat(message, force_path="paper_assistant")


def test_sufficient_evidence_answers_without_repair(db):
    doc_id = ingest_paper(db, SUFFICIENT_PAPER, "Retrieval Paper")
    result = run_paper_chat(db, "experiment dataset metric")
    assert result["paper_task"]["task_type"] == "experiment"
    assert result["evidence_grade"]["sufficient"] is True, result["evidence_grade"]
    assert len(result["retrieval_rounds"]) == 1, result["retrieval_rounds"]
    assert result["sources"], "缺少来源"
    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert any("【类型】experiment" in chunk.content for chunk in chunks)
    return doc_id


def test_missing_required_evidence_triggers_repair(db):
    doc_id = ingest_paper(db, INSUFFICIENT_PAPER, "Retrieval Paper Without Experiments")
    result = run_paper_chat(db, "ZypherNoExpAlpha42 experiment dataset metric")
    assert result["paper_task"]["task_type"] == "experiment"
    assert len(result["retrieval_rounds"]) >= 2, result["retrieval_rounds"]
    first_grade = result["retrieval_rounds"][0]["grade"]
    assert first_grade["sufficient"] is False, first_grade
    assert "缺少论文证据类型" in ";".join(first_grade["missing_aspects"])
    assert result["evidence_grade"]["sufficient"] is False, result["evidence_grade"]
    return doc_id


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_self_rag_regression").all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


def main():
    init_db()
    db = get_session_factory()()
    created_doc_ids = []
    try:
        cleanup_regression_docs(db)
        created_doc_ids.append(test_sufficient_evidence_answers_without_repair(db))
        for doc_id in created_doc_ids:
            IngestService(db).delete_document(doc_id)
        created_doc_ids = []
        cleanup_regression_docs(db)
        created_doc_ids.append(test_missing_required_evidence_triggers_repair(db))
        print("=== 论文助手 Self-RAG 回归测试通过 ===")
    finally:
        for doc_id in created_doc_ids:
            IngestService(db).delete_document(doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
