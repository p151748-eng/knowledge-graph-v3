"""
论文参考助手产品级回归测试。

覆盖产品验收核心指标：
1. 论文任务路由准确率。
2. 关键证据 TopK 召回与来源 chunk_type。
3. 回答关键点命中。
4. 证据不足时必须保留 evidence_grade 诊断，不能伪装高置信证据。

运行方式：
    python backend/tests/test_paper_product_regression.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import Document, get_session_factory, init_db
from services.chat import ChatService
from services.ingest import IngestService


class FakeResponse:
    def __init__(self, content):
        self.content = content


class ProductFakeLLM:
    provider = "fake"
    model = "fake-paper-product-regression"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            return {
                "relevance_score": 0.82,
                "support_score": 0.78,
                "coverage_score": 0.74,
                "freshness_required": "最新" in prompt or "2026" in prompt,
                "conflict_detected": False,
                "sufficient": True,
                "missing_aspects": [],
                "next_action": "answer",
                "reason": "产品评测证据相关",
            }
        if "CRAG 检索修正器" in prompt:
            return {
                "rewritten_query": "ProductEvalNoExp42 experiment dataset metric table",
                "expanded_queries": ["ProductEvalNoExp42 experiments", "ProductEvalNoExp42 results table"],
                "strategy": {"bm25": True, "vector": True, "graph": False, "graph_method": "none", "bm25_top_k": 14, "vector_top_k": 12, "graph_top_k": 8},
                "reason": "补充实验检索词",
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "方法分析专家" in text:
            return FakeResponse("方法回答：ProductEvalRAG 使用 ProductEvalFusion 和 multi-head self-attention 组织 encoder-decoder 流程。")
        if "实验分析专家" in text:
            return FakeResponse("实验回答：实验使用 WMT 2014 和 Natural Questions，指标包括 BLEU 与 F1。")
        if "方法对比专家" in text:
            return FakeResponse("对比回答：ProductEvalRAG 依赖检索融合与 self-attention，RNN baseline 依赖循环状态。")
        if "相关工作综述专家" in text:
            return FakeResponse("综述回答：相关工作从 recurrent sequence models 发展到 attention mechanisms，并连接检索增强生成研究。")
        if "论文写作辅助专家" in text:
            return FakeResponse("大纲回答：章节包括研究背景、ProductEvalFusion 方法、WMT 2014 实验、Natural Questions 分析和结论。")
        return FakeResponse("概述回答：论文解决知识密集型序列建模问题，提出 ProductEvalRAG，并报告 BLEU 与 F1 实验结果。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 29) % 101) / 101.0


MAIN_PAPER = """
# Product Evaluation Paper ProductEvalRAG42

Alice Researcher
2025

## Abstract
ProductEvalRAG42 studies retrieval augmented sequence modeling for knowledge-intensive question answering and machine translation.

## Introduction
The paper targets knowledge-intensive sequence modeling where parametric memory alone is insufficient.

## Method
Method: ProductEvalRAG
The method uses ProductEvalFusion with encoder-decoder layers, multi-head self-attention, BM25 retrieval and vector retrieval.

## Experiments
Dataset: WMT 2014, Natural Questions
Metric: BLEU, F1
ProductEvalRAG is evaluated on WMT 2014 machine translation and Natural Questions question answering.

| Model | Dataset | Metric | Score |
| --- | --- | --- | --- |
| ProductEvalRAG | WMT 2014 | BLEU | 31.2 |
| ProductEvalRAG | Natural Questions | F1 | 48.6 |
| RNN baseline | WMT 2014 | BLEU | 25.2 |

## Related Work
Prior work includes recurrent sequence models, attention mechanisms and retrieval augmented generation.

## Conclusion
The paper concludes that retrieval fusion and attention improve knowledge-intensive sequence modeling.

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
[2] Lewis et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. 2020.
"""

NO_EXPERIMENT_PAPER = """
# Product Evaluation Missing Experiments

Alice Researcher
2025

## Abstract
ProductEvalNoExp42 studies retrieval planning but does not report experiment tables.

## Method
Method: ProductEvalNoExp42
The method combines BM25 and vector retrieval.

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


CASES = [
    {
        "message": "ProductEvalRAG42 这篇论文主要解决什么问题？",
        "task": "overview",
        "expert": "paper_overview_expert",
        "required_chunk_types": {"abstract"},
        "answer_tokens": ["ProductEvalRAG", "知识密集型", "BLEU"],
    },
    {
        "message": "ProductEvalRAG42 方法部分怎么做的？",
        "task": "method",
        "expert": "paper_method_expert",
        "required_chunk_types": {"method"},
        "answer_tokens": ["ProductEvalFusion", "self-attention", "encoder-decoder"],
    },
    {
        "message": "ProductEvalRAG42 实验用了哪些数据集和指标？",
        "task": "experiment",
        "expert": "paper_experiment_expert",
        "required_chunk_types": {"experiment"},
        "answer_tokens": ["WMT 2014", "Natural Questions", "BLEU"],
    },
    {
        "message": "ProductEvalRAG42 和 RNN baseline 方法有什么区别？",
        "task": "compare",
        "expert": "paper_compare_expert",
        "required_chunk_types": {"method", "experiment"},
        "answer_tokens": ["RNN", "self-attention"],
    },
    {
        "message": "ProductEvalRAG42 帮我写相关工作综述",
        "task": "literature_review",
        "expert": "paper_literature_review_expert",
        "required_chunk_types": {"related_work", "reference"},
        "answer_tokens": ["recurrent", "attention", "检索增强"],
    },
    {
        "message": "ProductEvalRAG42 帮我生成论文大纲",
        "task": "outline",
        "expert": "paper_outline_expert",
        "required_chunk_types": {"abstract", "method", "experiment"},
        "answer_tokens": ["研究背景", "方法", "实验"],
    },
]


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source.in_(["paper_product_regression", "paper_product_no_exp_regression"])).all()
    for doc in docs:
        IngestService(db).delete_document(doc.id)


def source_chunk_types(result):
    return {source.get("chunk_type") for source in result.get("sources", []) if source.get("chunk_type")}


def main():
    init_db()
    db = get_session_factory()()
    created_doc_ids = []
    try:
        cleanup_regression_docs(db)
        ingest = IngestService(db)
        ingest.kg_extract.llm = ProductFakeLLM()
        created_doc_ids.append(ingest.ingest_text("Product Evaluation Paper ProductEvalRAG42", MAIN_PAPER, "paper_product_regression", ["paper", "product_eval"])["document_id"])
        created_doc_ids.append(ingest.ingest_text("Product Evaluation Missing Experiments", NO_EXPERIMENT_PAPER, "paper_product_no_exp_regression", ["paper", "product_eval"])["document_id"])

        service = ChatService(db)
        service.llm = ProductFakeLLM()

        routed = 0
        evidence_hit = 0
        answer_hit = 0
        for case in CASES:
            result = service.chat(case["message"], force_path="paper_assistant")
            assert result["path"] == "paper_assistant"
            assert result["paper_task"]["task_type"] == case["task"], result["paper_task"]
            assert result["paper_task"].get("expert") == case["expert"], result["paper_task"]
            routed += 1

            hit_types = source_chunk_types(result)
            assert case["required_chunk_types"] & hit_types, (case, hit_types, result["sources"])
            evidence_hit += 1

            assert any(token in result["response"] for token in case["answer_tokens"]), (case, result["response"])
            answer_hit += 1
            assert result["evidence_grade"].get("sufficient") is True, result["evidence_grade"]
            print(f"[PASS] {case['task']} evidence={sorted(hit_types)}")

        insufficient = service.chat("ProductEvalNoExp42 实验用了哪些数据集和指标？", force_path="paper_assistant")
        assert insufficient["paper_task"]["task_type"] == "experiment", insufficient["paper_task"]
        assert len(insufficient["retrieval_rounds"]) >= 2, insufficient["retrieval_rounds"]
        assert insufficient["evidence_grade"].get("sufficient") is False, insufficient["evidence_grade"]
        assert "缺少论文证据类型" in ";".join(insufficient["evidence_grade"].get("missing_aspects", [])), insufficient["evidence_grade"]

        total = len(CASES)
        assert routed / total >= 0.85
        assert evidence_hit / total >= 0.85
        assert answer_hit / total >= 0.80
        print(f"=== 产品级论文回归测试通过：routing={routed}/{total}, evidence={evidence_hit}/{total}, answer={answer_hit}/{total} ===")
    finally:
        for doc_id in created_doc_ids:
            IngestService(db).delete_document(doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
