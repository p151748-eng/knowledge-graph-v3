"""
真实论文网页抓取 + 结构化切分验收测试。

目标：
1. 从公开论文摘要页抓取多篇 AI 相关论文信息。
2. 转成论文 Markdown 文档后走 DocumentProcessor + TypeAwareChunker。
3. 严格检查 block/chunk 不缺标题、摘要、作者、年份、方法/实验/参考信息。
4. 导入本地 RAG 后验证 BM25/Hybrid 能召回对应论文证据。

运行方式：
    python backend/tests/test_real_paper_ingestion.py
"""

import html
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, get_session_factory, init_db
from services.document_processor import DocumentProcessor, TypeAwareChunker
from tools.doc_store import DocStoreTool
from tools.hybrid_search import HybridSearchTool


PAPERS = [
    {
        "id": "1706.03762",
        "title_token": "Attention Is All You Need",
        "required_terms": ["Transformer", "attention", "BLEU", "machine translation"],
    },
    {
        "id": "2005.11401",
        "title_token": "Retrieval-Augmented Generation",
        "required_terms": ["retrieval", "generation", "knowledge-intensive", "RAG"],
    },
    {
        "id": "2004.04906",
        "title_token": "Dense Passage Retrieval",
        "required_terms": ["open-domain", "question answering", "retrieval", "passage"],
    },
]


def fetch_arxiv(abs_id: str) -> Dict[str, str]:
    url = f"https://arxiv.org/abs/{abs_id}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 paper-ingestion-test/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AssertionError(f"无法抓取 arXiv {abs_id}: {exc}")

    title = clean_html(search_one(r'<h1 class="title mathjax">\s*<span[^>]*>Title:</span>(.*?)</h1>', raw, "title"))
    authors = clean_html(search_one(r'<div class="authors">\s*<span[^>]*>Authors:</span>(.*?)</div>', raw, "authors"))
    abstract = clean_html(search_one(r'<blockquote class="abstract mathjax">\s*<span[^>]*>Abstract:</span>(.*?)</blockquote>', raw, "abstract"))
    date = clean_html(search_one(r'<div class="dateline">\s*\[(.*?)\]\s*</div>', raw, "dateline"))
    comments = clean_html(search_optional(r'<td class="tablecell comments mathjax">(.*?)</td>', raw))
    subjects = clean_html(search_optional(r'<td class="tablecell subjects">(.*?)</td>', raw))
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", date)
    return {
        "id": abs_id,
        "url": url,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "year": year_match.group(1) if year_match else "",
        "comments": comments,
        "subjects": subjects,
    }


def search_one(pattern: str, text: str, field: str) -> str:
    match = re.search(pattern, text, re.S | re.I)
    if not match:
        raise AssertionError(f"arXiv 页面缺少字段: {field}")
    return match.group(1)


def search_optional(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.S | re.I)
    return match.group(1) if match else ""


def clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def paper_to_markdown(paper: Dict[str, str]) -> str:
    return f"""# {paper['title']}
{paper['authors']}
{paper['year']}
arXiv: {paper['id']}

## Abstract
{paper['abstract']}

## Method
This paper proposes or studies the core method described in the abstract. The method details are summarized from the public arXiv metadata and abstract.

## Experiments
The public arXiv page reports subjects and comments. Subjects: {paper['subjects']}. Comments: {paper['comments']}.

## References
[1] arXiv:{paper['id']} {paper['title']}.
"""


def assert_block_and_chunk_quality(paper: Dict[str, str], md: str, required_terms: List[str]) -> None:
    doc = DocumentProcessor().process(paper["title"], md, source=paper["url"])
    blocks = doc.blocks
    block_types = [block.type for block in blocks]
    assert doc.metadata.get("paper_title") == paper["title"], f"论文标题元数据错误: {paper['title']}"
    assert doc.metadata.get("year") == paper["year"], f"论文年份元数据错误: {paper['title']}"
    assert doc.metadata.get("authors"), f"作者缺失: {paper['title']}"
    for block_type in ["abstract", "method", "experiment", "reference"]:
        assert block_type in block_types, f"{paper['title']} 缺少 block: {block_type}, got={block_types}"

    all_block_text = "\n".join(block.text for block in blocks)
    for term in required_terms:
        assert term.lower() in all_block_text.lower(), f"{paper['title']} block 缺失关键信息: {term}"

    chunks = TypeAwareChunker(max_chars=700, overlap=80).chunk(doc)
    chunk_types = [chunk.chunk_type for chunk in chunks]
    for chunk_type in ["abstract", "method", "experiment", "reference"]:
        assert chunk_type in chunk_types, f"{paper['title']} 缺少 chunk: {chunk_type}, got={chunk_types}"
    assert len(chunks) <= 8, f"{paper['title']} chunk 过碎: {len(chunks)}"
    contents = [chunk.content for chunk in chunks]
    assert len(contents) == len(set(contents)), f"{paper['title']} 出现重复 chunk"
    assert any("【类型】abstract" in chunk.content and paper["abstract"][:80] in chunk.content for chunk in chunks), f"{paper['title']} 摘要 chunk 不完整"


def main():
    fetched = []
    for spec in PAPERS:
        paper = fetch_arxiv(spec["id"])
        assert spec["title_token"].lower() in paper["title"].lower(), f"标题不匹配: {paper['title']}"
        assert len(paper["abstract"]) >= 500, f"摘要文本过短，不适合严格测试: {paper['title']}"
        md = paper_to_markdown(paper)
        assert_block_and_chunk_quality(paper, md, spec["required_terms"])
        fetched.append((paper, md, spec))
        print(f"[PASS] 抓取并切分论文：{paper['title']} blocks/chunks 合格")

    init_db()
    db = get_session_factory()()
    created_ids: List[int] = []
    try:
        store = DocStoreTool(db)
        for paper, md, _ in fetched:
            result = store.store_document(
                title=paper["title"],
                content=md,
                source="real_paper_ingestion_test",
                source_url=paper["url"],
                tags=["paper", "arxiv", "ingestion_test"],
            )
            created_ids.append(result["id"])
            chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == result["id"]).count()
            assert 4 <= chunk_count <= 8, f"导入后 chunk 数异常: {paper['title']} chunks={chunk_count}"
            print(f"[PASS] 导入 RAG：doc_id={result['id']} chunks={chunk_count} title={paper['title']}")

        search = HybridSearchTool(db)
        for paper, _, spec in fetched:
            query = f"{spec['title_token']} 这篇论文主要解决什么问题？"
            result = search.execute(query, top_k=8, use_llm_router=False)
            context = result.get("context_text", "")
            assert spec["title_token"].lower() in context.lower(), f"未召回目标论文标题: {spec['title_token']}"
            assert any(term.lower() in context.lower() for term in spec["required_terms"]), f"未召回目标论文关键证据: {spec['title_token']}"
            assert any(hit.get("chunk_type") == "abstract" for hit in result.get("merged", [])), f"摘要 chunk 未进入 merged: {spec['title_token']}"
            print(f"[PASS] Hybrid 召回：{spec['title_token']} results={len(result.get('merged', []))}")

        print("\n=== 真实论文抓取、切分、导入、召回严格测试通过 ===")
    finally:
        for doc_id in created_ids:
            store.delete_document(doc_id)
        db.close()


if __name__ == "__main__":
    main()
