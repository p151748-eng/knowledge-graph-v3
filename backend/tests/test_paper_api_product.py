"""
论文产品化 API 回归测试。

验证目标：
1. /api/docs/{id}/chunks 能返回结构化 chunk 与 chunk_type。
2. /api/docs/{id}/paper-graph 能返回论文结构节点和边。
3. /api/kg/paper-graph/search 能查询论文结构图证据。

运行方式：
    python backend/tests/test_paper_api_product.py
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


class FakeLLM:
    provider = "fake"
    model = "fake-paper-api-product"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        class Response:
            content = "测试回答"
        return Response()

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 19) % 101) / 101.0


PAPER = """
# Product API Paper ProductApiUnique88

Alice Researcher
2024

## Abstract
ProductApiUnique88 This paper studies paper graph retrieval and evidence display APIs.

## Method
Method: ProductGraphRAG
The method connects paper sections, chunks, methods, datasets and metrics.

## Experiments
Dataset: WMT 2014
Metric: BLEU
ProductGraphRAG is evaluated with document chunk retrieval.

| Model | Dataset | Metric |
| --- | --- | --- |
| ProductGraphRAG | WMT 2014 | BLEU |

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_api_product_regression").all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        cleanup_regression_docs(db)
        ingest = IngestService(db)
        ingest.kg_extract.llm = FakeLLM()
        result = ingest.ingest_text(
            title="Product API Paper ProductApiUnique88",
            content=PAPER,
            source="paper_api_product_regression",
            tags=["paper", "api_product_regression"],
        )
        created_doc_id = result["document_id"]

        client = TestClient(app)

        chunks_resp = client.get(f"/api/docs/{created_doc_id}/chunks")
        assert chunks_resp.status_code == 200, chunks_resp.text
        chunks_data = chunks_resp.json()["data"]
        chunk_types = {chunk.get("chunk_type") for chunk in chunks_data["chunks"] if chunk.get("chunk_type")}
        assert {"abstract", "method", "experiment", "table", "reference"}.issubset(chunk_types), chunk_types

        filtered_resp = client.get(f"/api/docs/{created_doc_id}/chunks", params={"chunk_type": "experiment"})
        assert filtered_resp.status_code == 200, filtered_resp.text
        filtered_chunks = filtered_resp.json()["data"]["chunks"]
        assert filtered_chunks and all(chunk.get("chunk_type") == "experiment" for chunk in filtered_chunks)

        graph_resp = client.get(f"/api/docs/{created_doc_id}/paper-graph")
        assert graph_resp.status_code == 200, graph_resp.text
        graph_data = graph_resp.json()["data"]
        node_types = {node.get("type") for node in graph_data["nodes"]}
        relations = {edge.get("relation") for edge in graph_data["edges"]}
        assert "paper" in node_types and "section" in node_types and "chunk" in node_types, node_types
        assert "PAPER_HAS_SECTION" in relations and "SECTION_HAS_CHUNK" in relations, relations

        search_resp = client.get(
            "/api/kg/paper-graph/search",
            params={"q": "ProductApiUnique88 方法 数据集 指标", "method": "subgraph", "doc_id": created_doc_id},
        )
        assert search_resp.status_code == 200, search_resp.text
        search_data = search_resp.json()["data"]
        assert search_data["results"], search_data

        print("=== 论文产品化 API 回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
