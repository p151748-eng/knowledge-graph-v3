"""
论文参考助手 API 端到端测试。

覆盖从导入、chunk/图谱查看，到 paper chat 回答的完整产品路径。

运行方式：
    python backend/tests/test_paper_api_e2e.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from main import app
from models.db import Document, get_session_factory, init_db
from services.ingest import IngestService
import services.chat as chat_module


class FakeResponse:
    def __init__(self, content):
        self.content = content


class E2EFakeLLM:
    provider = "fake"
    model = "fake-paper-api-e2e"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            return {
                "relevance_score": 0.84,
                "support_score": 0.8,
                "coverage_score": 0.78,
                "freshness_required": False,
                "conflict_detected": False,
                "sufficient": True,
                "missing_aspects": [],
                "next_action": "answer",
                "reason": "端到端测试证据足够",
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "实验分析专家" in text:
            return FakeResponse("端到端实验回答：E2EPaperRAG 使用 S2ORC 数据集和 F1 指标评估。")
        return FakeResponse("端到端回答：E2EPaperRAG 用于论文参考助手检索。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 13) % 101) / 101.0


PAPER = """
# E2E Paper E2EPaperRAG99

Alice Researcher
2025

## Abstract
E2EPaperRAG99 studies end-to-end paper assistant retrieval.

## Method
Method: E2EPaperRAG
The method combines BM25, vector retrieval and paper graph retrieval.

## Experiments
Dataset: S2ORC
Metric: F1
E2EPaperRAG is evaluated on scientific paper question answering.

| Model | Dataset | Metric |
| --- | --- | --- |
| E2EPaperRAG | S2ORC | F1 |

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_api_e2e_regression").all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        cleanup_regression_docs(db)
        ingest = IngestService(db)
        ingest.kg_extract.llm = E2EFakeLLM()
        result = ingest.ingest_text(
            title="E2E Paper E2EPaperRAG99",
            content=PAPER,
            source="paper_api_e2e_regression",
            tags=["paper", "api_e2e_regression"],
        )
        created_doc_id = result["document_id"]

        client = TestClient(app)

        docs_resp = client.get("/api/docs", params={"search": "E2EPaperRAG99", "limit": 5})
        assert docs_resp.status_code == 200, docs_resp.text
        docs = docs_resp.json()["data"]["documents"]
        assert any(doc["id"] == created_doc_id for doc in docs), docs

        chunks_resp = client.get(f"/api/docs/{created_doc_id}/chunks", params={"chunk_type": "experiment"})
        assert chunks_resp.status_code == 200, chunks_resp.text
        chunks = chunks_resp.json()["data"]["chunks"]
        assert chunks and "S2ORC" in chunks[0]["content"], chunks

        graph_resp = client.get(f"/api/docs/{created_doc_id}/paper-graph")
        assert graph_resp.status_code == 200, graph_resp.text
        graph = graph_resp.json()["data"]
        assert graph["nodes"] and graph["edges"], graph

        search_resp = client.get("/api/kg/paper-graph/search", params={"q": "E2EPaperRAG99 数据集 指标", "method": "subgraph", "doc_id": created_doc_id})
        assert search_resp.status_code == 200, search_resp.text
        assert search_resp.json()["data"]["results"], search_resp.json()

        original_llm = chat_module.llm_manager
        chat_module.llm_manager = E2EFakeLLM()
        try:
            chat_resp = client.post("/api/chat/paper", json={"message": "E2EPaperRAG99 实验用了哪些数据集和指标？"})
        finally:
            chat_module.llm_manager = original_llm
        assert chat_resp.status_code == 200, chat_resp.text
        chat_data = chat_resp.json()["data"]
        assert chat_data["paper_task"]["task_type"] == "experiment", chat_data["paper_task"]
        assert chat_data["paper_task"].get("expert") == "paper_experiment_expert", chat_data["paper_task"]
        assert "S2ORC" in chat_data["response"] and "F1" in chat_data["response"], chat_data["response"]
        assert chat_data["sources"], "缺少回答来源"
        assert chat_data["evidence_grade"].get("sufficient") is True, chat_data["evidence_grade"]

        print("=== 论文参考助手 API 端到端测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
