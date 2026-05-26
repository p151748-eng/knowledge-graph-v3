"""
论文参考助手文档处理底座测试。

运行方式：
    python backend/tests/test_document_processor.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.document_processor import DocumentProcessor, TypeAwareChunker


PAPER_MD = """# GraphRAG for Scientific Literature
Alice Zhang, Bob Li
2024

## Abstract
This paper proposes GraphRAG-Sci for literature question answering. It retrieves papers and citation paths.

## Introduction
Scientific literature search needs evidence grounded answers and citation support.

## Related Work
BM25, dense retrieval, and graph retrieval are commonly used in RAG systems.

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


HTML_DOC = """
<html><body><script>ignore()</script><h1>Experiment Note</h1><p>We evaluate retrieval methods.</p>
<table><tr><th>Model</th><th>MRR</th></tr><tr><td>Hybrid</td><td>0.91</td></tr></table>
<pre>score = evaluate()</pre><footer>ignore footer</footer></body></html>
"""

ZH_PAPER_TEXT = """中文知识图谱论文
张三，李四
2024

摘要
本文提出一种面向论文参考助手的知识图谱增强检索方法。

第一章 绪论
论文参考助手需要理解中文文献的章节结构和证据来源。

二、文献综述
国内外研究现状表明，混合检索和图检索常用于复杂问答。

3. 研究方法
本文采用GraphRAG-CN模型构建论文结构图，并结合BM25和向量检索。

第4章 实验结果与分析
数据集：中文论文集。指标：准确率、召回率和F1。
实验结果表明，该方法提升了召回效果。

（五）总结与展望
本文方法能够改善中文论文问答质量。

参考文献
[1] 张三. 知识图谱研究. 2023.
"""


def block_types(doc):
    return [block.type for block in doc.blocks]


def test_markdown_blocks_are_complete():
    doc = DocumentProcessor().process("GraphRAG paper", PAPER_MD, source="paper.md")
    types = block_types(doc)
    assert "abstract" in types
    assert "related_work" in types
    assert "method" in types
    assert "experiment" in types
    assert "table" in types
    assert "code" in types
    assert "reference" in types
    assert doc.metadata["paper_title"] == "GraphRAG for Scientific Literature"
    assert doc.metadata["year"] == "2024"
    all_text = "\n".join(block.text for block in doc.blocks)
    for key in ["GraphRAG-Sci", "hybrid_search", "S2ORC", "Attention Is All You Need"]:
        assert key in all_text


def test_chunk_types_and_metadata():
    doc = DocumentProcessor().process("GraphRAG paper", PAPER_MD, source="paper.md")
    chunks = TypeAwareChunker(max_chars=500).chunk(doc)
    types = [chunk.chunk_type for chunk in chunks]
    assert "abstract" in types
    assert "method" in types
    assert "experiment" in types
    assert "table" in types
    assert "code" in types
    assert "reference" in types
    method = next(chunk for chunk in chunks if chunk.chunk_type == "method")
    assert "【类型】method" in method.content
    assert method.metadata["paper_title"] == "GraphRAG for Scientific Literature"
    experiment = next(chunk for chunk in chunks if chunk.chunk_type == "experiment")
    assert "BLEU" in experiment.content and "S2ORC" in experiment.content


def test_html_blocks_keep_table_and_code_without_noise():
    doc = DocumentProcessor().process("Experiment Note", HTML_DOC, source="note.html")
    chunks = TypeAwareChunker().chunk(doc)
    text = "\n".join(chunk.content for chunk in chunks)
    assert "ignore()" not in text
    assert "ignore footer" not in text
    assert "Experiment Note" in text
    assert "| Model | MRR |" in text
    assert "score = evaluate()" in text
    assert "table" in [chunk.chunk_type for chunk in chunks]
    assert "code" in [chunk.chunk_type for chunk in chunks]


def test_content_list_conversion():
    content_list = [
        {"type": "text", "text_level": 1, "text": "Abstract"},
        {"type": "text", "text": "This paper studies retrieval augmented generation."},
        {"type": "table", "table_body": "| Method | F1 |\n| --- | --- |\n| RAG | 80 |"},
        {"type": "equation", "latex": "F1=2PR/(P+R)"},
    ]
    doc = DocumentProcessor().from_content_list("RAG paper", content_list)
    chunks = TypeAwareChunker().chunk(doc)
    text = "\n".join(chunk.content for chunk in chunks)
    assert "retrieval augmented generation" in text
    assert "RAG" in text
    assert "F1=2PR" in text


def test_plain_text_repeated_content_is_not_duplicated_by_overlap():
    content = """
Query Router 负责识别用户意图。

BM25SearchTool 负责精确关键词召回。
Vector Search 负责语义召回。
GraphRetrievalService 负责图上关系检索。

系统中存在如下关系：Query Router 生成 RetrievalPlan。
""" * 3
    doc = DocumentProcessor().process("Hybrid retrieval note", content, source="note.txt")
    chunks = TypeAwareChunker(max_chars=1000, overlap=120).chunk(doc)
    assert len(chunks) <= 4
    contents = [chunk.content for chunk in chunks]
    assert len(contents) == len(set(contents))
    assert all("【类型】paragraph" in chunk.content for chunk in chunks)
    assert "Query Router" in "\n".join(contents)
    assert "GraphRetrievalService" in "\n".join(contents)


def test_chinese_paper_headings_are_typed():
    doc = DocumentProcessor().process("中文知识图谱论文", ZH_PAPER_TEXT, source="paper.pdf", file_type="pdf")
    chunks = TypeAwareChunker(max_chars=500).chunk(doc)
    types = [chunk.chunk_type for chunk in chunks]
    assert "abstract" in types
    assert "related_work" in types
    assert "method" in types
    assert "experiment" in types
    assert "conclusion" in types
    assert "reference" in types
    assert doc.metadata["language"] == "zh"
    method = next(chunk for chunk in chunks if chunk.chunk_type == "method")
    assert "GraphRAG-CN" in method.content
    experiment = next(chunk for chunk in chunks if chunk.chunk_type == "experiment")
    assert "准确率" in experiment.content and "中文论文集" in experiment.content


if __name__ == "__main__":
    test_markdown_blocks_are_complete()
    test_chunk_types_and_metadata()
    test_html_blocks_keep_table_and_code_without_noise()
    test_content_list_conversion()
    test_plain_text_repeated_content_is_not_duplicated_by_overlap()
    test_chinese_paper_headings_are_typed()
    print("=== document_processor 测试通过 ===")
