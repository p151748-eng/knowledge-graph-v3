"""
论文 Manager-Agent 专家调度回归测试。

验证目标：
1. PaperAssistant 作为 Manager 能按任务类型调度不同专家 Agent。
2. 每个专家 Agent 都基于同一套检索证据生成回答。
3. paper_task 返回 expert 字段，便于前端/调试展示调度结果。

运行方式：
    python backend/tests/test_paper_manager_agents.py
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


class FakeLLM:
    provider = "fake"
    model = "fake-paper-manager-agents"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        if "CRAG 证据评估器" in prompt:
            return {
                "relevance_score": 0.82,
                "support_score": 0.78,
                "coverage_score": 0.76,
                "freshness_required": False,
                "conflict_detected": False,
                "sufficient": True,
                "missing_aspects": [],
                "next_action": "answer",
                "reason": "证据覆盖论文任务",
            }
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "方法分析专家" in text:
            return FakeResponse("方法专家回答：Transformer 使用 encoder-decoder 和 multi-head self-attention 组织模型流程。")
        if "实验分析专家" in text:
            return FakeResponse("实验专家回答：实验使用 WMT 2014 数据集，并以 BLEU 作为主要指标。")
        if "方法对比专家" in text:
            return FakeResponse("对比专家回答：Transformer 依赖 self-attention，RNN baseline 依赖循环结构。")
        if "相关工作综述专家" in text:
            return FakeResponse("综述专家回答：相关工作从 recurrent sequence models 发展到 attention mechanisms。")
        if "论文写作辅助专家" in text:
            return FakeResponse("写作专家回答：大纲包括研究背景、方法设计、实验分析和结论。")
        return FakeResponse("概述专家回答：论文提出 Transformer，用注意力机制解决序列建模问题。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 23) % 101) / 101.0


PAPER = """
# Manager Agent Paper ManagerUnique77

Alice Researcher
2024

## Abstract
ManagerUnique77 This paper studies Transformer models for sequence transduction and paper assistant retrieval.

## Introduction
Sequence models often rely on recurrent neural networks. Transformer uses attention mechanisms instead.

## Method
Method: Transformer
The method uses encoder-decoder layers and multi-head self-attention.

## Experiments
Dataset: WMT 2014
Metric: BLEU
Transformer is compared with an RNN baseline on machine translation.

| Model | Dataset | Metric |
| --- | --- | --- |
| Transformer | WMT 2014 | BLEU |
| RNN baseline | WMT 2014 | BLEU |

## Related Work
Prior work includes recurrent sequence models and attention mechanisms.

## Conclusion
The paper concludes that attention-based sequence transduction is effective.

## References
[1] Vaswani et al. Attention Is All You Need. 2017.
"""


CASES = [
    ("ManagerUnique77 这篇论文主要解决什么问题？", "overview", "paper_overview_expert", "概述专家回答"),
    ("ManagerUnique77 这篇论文的方法部分怎么做的？", "method", "paper_method_expert", "方法专家回答"),
    ("ManagerUnique77 实验用了哪些数据集和指标？", "experiment", "paper_experiment_expert", "实验专家回答"),
    ("ManagerUnique77 Transformer 和 RNN 方法有什么区别？", "compare", "paper_compare_expert", "对比专家回答"),
    ("ManagerUnique77 帮我基于这篇论文写相关工作综述", "literature_review", "paper_literature_review_expert", "综述专家回答"),
    ("ManagerUnique77 帮我生成论文大纲", "outline", "paper_outline_expert", "写作专家回答"),
]


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_manager_agent_regression").all()
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
            title="Manager Agent Paper ManagerUnique77",
            content=PAPER,
            source="paper_manager_agent_regression",
            tags=["paper", "manager_agent_regression"],
        )
        created_doc_id = result["document_id"]

        service = ChatService(db)
        service.llm = FakeLLM()
        for message, expected_task, expected_expert, answer_token in CASES:
            result = service.chat(message, force_path="paper_assistant")
            assert result["path"] == "paper_assistant"
            assert result["paper_task"]["task_type"] == expected_task, result["paper_task"]
            assert result["paper_task"].get("expert") == expected_expert, result["paper_task"]
            assert answer_token in result["response"], result["response"]
            assert result["sources"], "缺少来源"
            print(f"[PASS] {expected_task} -> {expected_expert}")

        print("=== 论文 Manager-Agent 专家调度回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
