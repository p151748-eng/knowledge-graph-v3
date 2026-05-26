"""
参考文献解析回归测试。

运行方式：
    python backend/tests/test_reference_parser.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.document_processor.reference_parser import ReferenceParser


REFERENCE_CHUNK = """
【论文】Transformer Experiment Graph
【章节】References
【类型】reference
【引用】
【内容】
[1] Ashish Vaswani, Noam Shazeer, Niki Parmar et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762
[2] Patrick Lewis et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS, 2020. doi:10.5555/3495724.3496517
[3] GraphRAG: Graph-based Retrieval Augmented Generation. Microsoft Research, 2024.
"""


def main():
    parser = ReferenceParser()
    references = parser.parse(REFERENCE_CHUNK)
    assert len(references) == 3, f"引用拆分数量错误：{references}"

    first = references[0]
    assert first.citation_key == "ref-1"
    assert first.authors.startswith("Ashish Vaswani"), first
    assert first.title == "Attention Is All You Need", first
    assert first.venue == "NeurIPS, 2017", first
    assert first.year == "2017", first
    assert first.arxiv_id == "1706.03762", first

    second = references[1]
    assert second.citation_key == "ref-2"
    assert second.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", second
    assert second.year == "2020", second
    assert second.doi == "10.5555/3495724.3496517", second

    third = references[2]
    assert third.title == "GraphRAG: Graph-based Retrieval Augmented Generation", third
    assert third.year == "2024", third

    line_refs = parser.parse("Vaswani et al. Attention Is All You Need. NeurIPS, 2017.")
    assert len(line_refs) == 1
    assert line_refs[0].title == "Attention Is All You Need", line_refs[0]
    assert line_refs[0].citation_key == "vaswani2017", line_refs[0]

    print("=== 参考文献解析回归测试通过 ===")


if __name__ == "__main__":
    main()
