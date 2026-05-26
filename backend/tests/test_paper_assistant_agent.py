"""
论文参考助手 Agent 层回归测试。

验证目标：
1. PaperTaskRouter 能把论文参考问题路由到对应任务。
2. PaperAssistantAgent 能按任务偏好优先使用论文结构化 chunk。
3. ChatService paper_assistant 路径能返回任务信息、来源和中文回答。

运行方式：
    python backend/tests/test_paper_assistant_agent.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.paper_task_router import PaperTaskRouter
from models.db import Document, DocumentChunk, get_session_factory, init_db
from services.chat import ChatService
from services.ingest import IngestService


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    provider = "fake"
    model = "fake-paper-agent"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {}

    def complete(self, prompt, system_prompt="", **kwargs):
        text = system_prompt + "\n" + prompt
        if "【回答风格】\nmethod_comparison" in text:
            return FakeResponse("方法对比：Transformer 依赖 self-attention，RNN 依赖循环结构；证据来自方法章节和实验章节。")
        if "【回答风格】\nexperiment_analysis" in text:
            return FakeResponse("实验分析：论文在 WMT 2014 上使用 BLEU 指标评估 Transformer，并报告翻译效果。")
        if "【回答风格】\nliterature_review" in text:
            return FakeResponse("相关工作综述：该方向从循环序列模型发展到注意力机制，并引用了神经机器翻译相关工作。")
        if "【回答风格】\nwriting_outline" in text:
            return FakeResponse("论文大纲：一、研究背景；二、方法；三、实验；四、结论，各节基于摘要、方法和实验证据。")
        return FakeResponse("论文概述：这篇论文主要解决序列建模问题，提出 Transformer，并使用 self-attention 替代循环结构。")

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 31) % 101) / 101.0


PAPER = """
# Attention Is All You Need

Ashish Vaswani et al.
2017

## Abstract

The Transformer is a new network architecture based solely on attention mechanisms. It avoids recurrence and convolutions while improving machine translation quality.

## Introduction

Sequence transduction models usually rely on recurrent neural networks. This paper proposes a simpler architecture based on self-attention.

## Model Architecture

The Transformer follows an encoder-decoder architecture. Multi-head attention allows the model to jointly attend to information from different representation subspaces.

```python
def multi_head_attention(query, key, value):
    return attention(query, key, value)
```

## Experiments

The model is evaluated on WMT 2014 English-German and English-French machine translation tasks. The main metric is BLEU.

| Model | Dataset | BLEU |
| --- | --- | --- |
| Transformer | WMT 2014 En-De | 28.4 |
| RNN baseline | WMT 2014 En-De | 25.2 |

## Related Work

Prior neural machine translation systems used recurrent sequence models and attention mechanisms.

## Conclusion

The Transformer shows that attention alone can produce strong sequence transduction models.

## References

[1] Neural Machine Translation by Jointly Learning to Align and Translate.
"""

UNIQUE_MARKER = "PaperAssistantUnique42"
PAPER = PAPER.replace("# Attention Is All You Need", f"# Attention Is All You Need {UNIQUE_MARKER}")
PAPER = PAPER.replace("The Transformer is a new network architecture", f"{UNIQUE_MARKER} The Transformer is a new network architecture")


CASES = [
    ("这篇论文主要解决什么问题？", "overview", ["论文概述", "Transformer"]),
    ("这篇论文的方法部分怎么做的？", "method", ["Transformer", "self-attention"]),
    ("实验用了哪些数据集和指标？", "experiment", ["实验分析", "WMT 2014", "BLEU"]),
    ("Transformer 和 RNN 方法有什么区别？", "compare", ["方法对比", "RNN", "self-attention"]),
    ("帮我基于这篇论文写相关工作综述", "literature_review", ["相关工作综述", "循环", "注意力"]),
    ("帮我生成论文大纲", "outline", ["论文大纲", "研究背景", "实验"]),
]


def cleanup_regression_docs(db):
    docs = db.query(Document).filter(Document.source == "paper_assistant_regression").all()
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
            title="Attention Is All You Need",
            content=PAPER,
            source="paper_assistant_regression",
            tags=["paper", "agent_regression"],
        )
        created_doc_id = result["document_id"]
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).all()
        assert len(chunks) >= 5, f"论文切片不足：{len(chunks)}"
        all_chunks = "\n".join(chunk.content for chunk in chunks)
        for chunk_type in ["abstract", "method", "experiment", "table", "related_work", "reference"]:
            assert f"【类型】{chunk_type}" in all_chunks, f"缺少论文 chunk_type={chunk_type}"

        service = ChatService(db)
        service.llm = FakeLLM()
        router = PaperTaskRouter()
        for message, expected_task, answer_tokens in CASES:
            task_plan = router.route(message)
            assert task_plan.task_type == expected_task, f"{message} task={task_plan.task_type}, expected={expected_task}"
            result = service.chat(f"{UNIQUE_MARKER} {message}", force_path="paper_assistant")
            assert result["path"] == "paper_assistant"
            assert result["paper_task"]["task_type"] == expected_task
            answer = result["response"]
            assert answer and not answer.startswith("[错误]"), answer
            assert any(token in answer for token in answer_tokens), f"回答未包含预期信息：{answer_tokens}, answer={answer}"
            assert result["sources"], "缺少来源"
            source_types = {source.get("chunk_type") for source in result["sources"] if source.get("chunk_type")}
            assert source_types, "来源缺少 chunk_type"
            print(f"[PASS] {message} -> {expected_task}, sources={sorted(source_types)}")

        print("\n=== 论文参考助手 Agent 回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        cleanup_regression_docs(db)
        db.close()


if __name__ == "__main__":
    main()
