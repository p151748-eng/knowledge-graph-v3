"""
论文引用图构建回归测试。

验证目标：
1. reference chunk 会被拆成单条 reference 节点。
2. 构建 PAPER_CITES_PAPER / SECTION_MENTIONS_REFERENCE / CHUNK_MENTIONS_REFERENCE 引用边。
3. GraphRetrievalService 能检索引用链路。

运行方式：
    python backend/tests/test_citation_graph.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import Edge, Node, get_session_factory, init_db
from services.graph_retrieval import GraphRetrievalService
from services.ingest import IngestService


class FakeLLM:
    provider = "fake"
    model = "fake-citation-graph"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {"entities": [], "relations": []}

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 19) % 101) / 101.0


PAPER = """
# Citation Graph for Scientific RAG

Lin Chen, Mei Wang
2026

## Abstract

This paper studies CitationGraphRAG for literature review generation.

## Method

Method: CitationGraphRAG
CitationGraphRAG connects paper structure with citation graph retrieval.

## Related Work

Prior work includes Transformer and Retrieval-Augmented Generation.

## References

[1] Ashish Vaswani, Noam Shazeer, Niki Parmar et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762
[2] Patrick Lewis et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS, 2020. doi:10.5555/3495724.3496517
[3] GraphRAG: Graph-based Retrieval Augmented Generation. Microsoft Research, 2024.
"""

REQUIRED_CITATION_EDGES = {
    "PAPER_CITES_PAPER",
    "SECTION_MENTIONS_REFERENCE",
    "CHUNK_MENTIONS_REFERENCE",
    "REFERENCE_RESOLVES_TO_PAPER",
}


def doc_id_filter(items, doc_id):
    return [item for item in items if doc_id in (item.source_doc_ids or [])]


def result_text(hits):
    return "\n".join(hit.get("description") or hit.get("name") or "" for hit in hits)


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        ingest = IngestService(db)
        ingest.kg_extract.llm = FakeLLM()
        result = ingest.ingest_text(
            title="Citation Graph for Scientific RAG",
            content=PAPER,
            source="citation_graph_regression",
            tags=["paper", "citation_graph"],
        )
        created_doc_id = result["document_id"]

        nodes = doc_id_filter(db.query(Node).all(), created_doc_id)
        reference_nodes = [node for node in nodes if node.type == "reference"]
        assert len(reference_nodes) >= 3, f"引用节点数量不足：{[(n.name, n.type) for n in reference_nodes]}"
        assert any((node.properties or {}).get("title") == "Attention Is All You Need" for node in reference_nodes), "缺少单条引用节点 Attention"

        cited_papers = [node for node in nodes if node.type == "paper" and (node.properties or {}).get("is_cited_reference")]
        assert any(node.name == "Attention Is All You Need" for node in cited_papers), "缺少被引论文节点 Attention"
        assert any("Retrieval-Augmented Generation" in node.name for node in cited_papers), "缺少被引论文节点 RAG"

        edges = doc_id_filter(db.query(Edge).all(), created_doc_id)
        edge_types = {edge.relation for edge in edges}
        missing_edges = REQUIRED_CITATION_EDGES - edge_types
        assert not missing_edges, f"缺少引用图边：{missing_edges}, got={sorted(edge_types)}"

        graph = GraphRetrievalService(db)
        hits = graph.search(
            method="subgraph",
            entities=["Citation Graph for Scientific RAG"],
            seed_node_ids=[],
            query="这篇论文引用了哪些参考文献？",
            limit=16,
            depth=2,
        )
        text = result_text(hits)
        assert "PAPER_CITES_PAPER" in text or any(hit.get("relation") == "PAPER_CITES_PAPER" for hit in hits), text
        assert "Attention Is All You Need" in text, text
        assert "Retrieval-Augmented Generation" in text, text

        print("=== 论文引用图构建回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
