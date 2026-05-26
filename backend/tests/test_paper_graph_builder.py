"""
论文结构图构建回归测试。

验证目标：
1. PaperGraphBuilder 能为论文、章节、chunk、表格、代码、方法、数据集和指标建节点。
2. 能写入 PAPER_HAS_SECTION / SECTION_HAS_CHUNK / NEXT_CHUNK 等结构边。
3. IngestService 导入论文时会自动触发论文结构图构建。

运行方式：
    python backend/tests/test_paper_graph_builder.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, Edge, Node, get_session_factory, init_db
from services.ingest import IngestService
from services.paper_graph_builder import PaperGraphBuilder


class FakeLLM:
    provider = "fake"
    model = "fake-paper-graph"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {"entities": [], "relations": []}

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 17) % 101) / 101.0


PAPER = """
# GraphRAG for Scientific Literature

Alice Zhang, Bob Li
2024

## Abstract

This paper proposes GraphRAG-Sci for scientific literature question answering.

## Method

Method: GraphRAG-Sci
The method builds a paper graph and uses hybrid retrieval.

```python
def retrieve(query):
    return hybrid_search(query)
```

## Experiments

Dataset: S2ORC, WMT14
The model reports BLEU and F1 improvements.

| Model | Dataset | Metric | Score |
| --- | --- | --- | --- |
| GraphRAG-Sci | S2ORC | F1 | 88.1 |

## Conclusion

Graph structure improves literature reasoning.

## References

[1] Vaswani et al. Attention Is All You Need. 2017.
"""


REQUIRED_NODE_TYPES = {"paper", "section", "chunk", "table", "code", "method", "dataset", "metric", "reference"}
REQUIRED_EDGE_TYPES = {
    "PAPER_HAS_SECTION",
    "SECTION_HAS_CHUNK",
    "NEXT_CHUNK",
    "PREV_CHUNK",
    "SECTION_HAS_TABLE",
    "SECTION_HAS_CODE",
    "METHOD_EVALUATED_ON_DATASET",
    "METHOD_REPORTED_METRIC",
}


def doc_id_filter(items, doc_id):
    return [item for item in items if doc_id in (item.source_doc_ids or [])]


def assert_graph_for_doc(db, doc_id):
    nodes = doc_id_filter(db.query(Node).all(), doc_id)
    node_types = {node.type for node in nodes}
    missing_nodes = REQUIRED_NODE_TYPES - node_types
    assert not missing_nodes, f"缺少节点类型：{missing_nodes}, got={sorted(node_types)}"

    edges = doc_id_filter(db.query(Edge).all(), doc_id)
    edge_types = {edge.relation for edge in edges}
    missing_edges = REQUIRED_EDGE_TYPES - edge_types
    assert not missing_edges, f"缺少边类型：{missing_edges}, got={sorted(edge_types)}"

    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    chunk_nodes = [node for node in nodes if node.type == "chunk"]
    assert len(chunk_nodes) == len(chunks), f"chunk 节点数量不一致：nodes={len(chunk_nodes)}, chunks={len(chunks)}"

    graph_nodes = [node for node in nodes if node.name == "GraphRAG-Sci" and node.type == "method"]
    assert graph_nodes, "缺少方法节点 GraphRAG-Sci"
    assert any(node.name == "S2ORC" and node.type == "dataset" for node in nodes), "缺少数据集节点 S2ORC"
    assert any(node.name == "BLEU" and node.type == "metric" for node in nodes), "缺少指标节点 BLEU"


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        ingest = IngestService(db)
        ingest.kg_extract.llm = FakeLLM()
        result = ingest.ingest_text(
            title="GraphRAG for Scientific Literature",
            content=PAPER,
            source="paper_graph_regression",
            tags=["paper", "graph_regression"],
        )
        created_doc_id = result["document_id"]
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).all()
        assert chunks, "导入后缺少 DocumentChunk"

        assert_graph_for_doc(db, created_doc_id)

        second = PaperGraphBuilder(db).build_for_document(created_doc_id)
        assert second["nodes_created"] == 0, f"重复构建不应新增节点：{second}"
        assert second["edges_created"] == 0, f"重复构建不应新增边：{second}"

        print("=== 论文结构图构建回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
