"""
论文图检索回归测试。

验证目标：
1. GraphRetrievalService 能检索论文章节结构。
2. 能通过 paper path 找到方法到数据集/指标/表格的实验证据。
3. HybridSearchTool 使用 graph plan 时能返回论文图证据。

运行方式：
    python backend/tests/test_paper_graph_retrieval.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, Node, get_session_factory, init_db
from services.graph_retrieval import GraphRetrievalService
from services.ingest import IngestService
from tools.hybrid_search import HybridSearchTool


class FakeLLM:
    provider = "fake"
    model = "fake-paper-graph-retrieval"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {"entities": [], "relations": []}

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 23) % 101) / 101.0


PAPER = """
# Transformer Experiment Graph

Chen Wang et al.
2025

## Abstract

This paper studies TransformerGraph for graph-aware scientific paper retrieval.

## Method

Method: TransformerGraph
TransformerGraph combines self-attention with citation graph retrieval.

```python
def transform_graph(x):
    return attention(x)
```

## Experiments

Dataset: S2ORC, WMT14
The evaluation reports BLEU, F1 and accuracy.

| Model | Dataset | Metric | Score |
| --- | --- | --- | --- |
| TransformerGraph | S2ORC | F1 | 91.2 |
| TransformerGraph | WMT14 | BLEU | 29.1 |

## Related Work

Prior systems used Transformer, RNN and citation graph search.

## References

[1] Attention Is All You Need. 2017.
"""


def relation_set(hits):
    return {hit.get("relation") for hit in hits}


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
            title="Transformer Experiment Graph",
            content=PAPER,
            source="paper_graph_retrieval_regression",
            tags=["paper", "graph_retrieval"],
        )
        created_doc_id = result["document_id"]
        assert db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).count() >= 6

        graph = GraphRetrievalService(db)
        structure_hits = graph.search(
            method="subgraph",
            entities=["Transformer Experiment Graph"],
            seed_node_ids=[],
            query="这篇论文有哪些章节结构？",
            limit=12,
            depth=2,
        )
        assert structure_hits, "论文结构图检索无结果"
        assert "PAPER_HAS_SECTION" in relation_set(structure_hits), f"结构检索缺少 PAPER_HAS_SECTION: {structure_hits}"
        assert any("SECTION_HAS_CHUNK" == hit.get("relation") for hit in structure_hits), "结构检索缺少 SECTION_HAS_CHUNK"

        experiment_hits = graph.search(
            method="path",
            entities=["TransformerGraph"],
            seed_node_ids=[],
            query="TransformerGraph 方法在哪些数据集和指标上评估？",
            limit=12,
            depth=3,
        )
        text = result_text(experiment_hits)
        assert experiment_hits, "实验路径图检索无结果"
        assert "METHOD_EVALUATED_ON_DATASET" in text, f"实验路径缺少数据集关系：{text}"
        assert "METHOD_REPORTED_METRIC" in text, f"实验路径缺少指标关系：{text}"
        assert any(token in text for token in ["S2ORC", "WMT14"]), f"实验路径缺少数据集名称：{text}"
        assert any(token in text for token in ["BLEU", "F1"]), f"实验路径缺少指标名称：{text}"

        hybrid = HybridSearchTool(db, FakeLLM())
        hybrid_result = hybrid.execute(
            "TransformerGraph 的实验用了哪些数据集和指标？",
            top_k=8,
            use_llm_router=False,
            plan_override={
                "graph": True,
                "graph_method": "path",
                "intent": "relation",
                "entities": ["TransformerGraph"],
                "graph_top_k": 8,
                "graph_depth": 3,
            },
        )
        graph_hits = hybrid_result.get("graph_hits", [])
        assert graph_hits, "HybridSearchTool 缺少 graph_hits"
        graph_text = result_text(graph_hits)
        assert "METHOD_EVALUATED_ON_DATASET" in graph_text or "METHOD_REPORTED_METRIC" in graph_text, graph_text
        print("=== 论文图检索回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
