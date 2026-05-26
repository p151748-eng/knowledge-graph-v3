"""
arXiv HTML 全文抓取 + 真实章节切分严格测试。

目标：验证不依赖手写 Markdown 模板时，真实论文 HTML 全文能被转换为稳定章节 block/chunk。

运行方式：
    python backend/tests/test_arxiv_fulltext_processor.py
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

from services.document_processor import DocumentProcessor, TypeAwareChunker


FULLTEXT_PAPERS = [
    {
        "id": "1706.03762",
        "title_token": "Attention Is All You Need",
        "required_sections": ["abstract", "introduction", "method", "experiment", "conclusion", "reference"],
        "required_terms": ["Transformer", "multi-head attention", "BLEU", "WMT 2014", "encoder", "decoder"],
    },
    {
        "id": "2005.11401",
        "title_token": "Retrieval-Augmented Generation",
        "required_sections": ["abstract", "introduction", "method", "experiment", "reference"],
        "required_terms": ["RAG", "retriever", "generator", "knowledge-intensive", "Natural Questions"],
    },
]


def fetch_arxiv_html(abs_id: str) -> str:
    url = f"https://arxiv.org/html/{abs_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 arxiv-html-fulltext-test/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AssertionError(f"无法抓取 arXiv HTML 全文 {abs_id}: {exc}")
    if len(text) < 30000:
        raise AssertionError(f"arXiv HTML 全文过短，可能未成功获取: {abs_id}, len={len(text)}")
    return text


def html_to_markdown(html_text: str) -> str:
    title = extract_title(html_text)
    body = re.sub(r"<dialog[\s\S]*?</dialog>|<header[\s\S]*?</header>|<script[\s\S]*?</script>|<style[\s\S]*?</style>|<nav[\s\S]*?</nav>|<footer[\s\S]*?</footer>", "\n", html_text, flags=re.I)
    article_match = re.search(r"<article[\s\S]*?</article>", body, flags=re.I)
    if article_match:
        body = article_match.group(0)
    tokens = re.findall(
        r"<h[1-6][\s\S]*?</h[1-6]>|<blockquote[^>]*class=[\"'][^\"']*ltx_abstract[^\"']*[\"'][\s\S]*?</blockquote>|<table[\s\S]*?</table>|<pre[\s\S]*?</pre>|<p[\s\S]*?</p>|<li[\s\S]*?</li>",
        body,
        flags=re.I,
    )
    lines = [f"# {title}"] if title else []
    for token in tokens:
        lower = token.lower()
        if lower.startswith("<h"):
            level = re.match(r"<h([1-6])", lower).group(1)
            heading = clean_html(token)
            heading = normalize_heading(heading)
            if heading:
                lines.append("#" * int(level) + " " + heading)
        elif "ltx_abstract" in lower:
            abstract = clean_html(token)
            abstract = re.sub(r"^abstract\s*", "", abstract, flags=re.I).strip()
            if abstract:
                lines.append("## Abstract")
                lines.append(abstract)
        elif lower.startswith("<table"):
            table_text = clean_html(token)
            if table_text:
                lines.append("## Table")
                lines.append(table_text)
        elif lower.startswith("<pre"):
            code = clean_html(token)
            if code:
                lines.append("```")
                lines.append(code)
                lines.append("```")
        else:
            paragraph = clean_html(token)
            if paragraph and len(paragraph) >= 20:
                lines.append(paragraph)
    markdown = "\n\n".join(lines)
    if len(markdown) < 10000:
        raise AssertionError(f"HTML 转 Markdown 后文本过短: len={len(markdown)}")
    return markdown


def extract_title(html_text: str) -> str:
    for pattern in [r"<h1[^>]*class=[\"'][^\"']*ltx_title[^\"']*[\"'][^>]*>([\s\S]*?)</h1>", r"<title>([\s\S]*?)</title>"]:
        match = re.search(pattern, html_text, flags=re.I)
        if match:
            title = clean_html(match.group(1))
            title = re.sub(r"\s*\|\s*arXiv.*$", "", title, flags=re.I).strip()
            if title:
                return title
    return ""


def normalize_heading(heading: str) -> str:
    heading = re.sub(r"^(\d+(?:\.\d+)*|[IVX]+)\s*", "", heading.strip(), flags=re.I)
    heading = re.sub(r"\s+", " ", heading).strip()
    lower = heading.lower()
    aliases = {
        "intro": "Introduction",
        "introduction": "Introduction",
        "background": "Related Work",
        "model architecture": "Method",
        "model": "Method",
        "experiments": "Experiments",
        "conclusions": "Conclusion",
        "refs": "References",
        "bibliography": "References",
    }
    return aliases.get(lower, heading)


def clean_html(value: str) -> str:
    value = re.sub(r"<math[\s\S]*?</math>", " ", value or "", flags=re.I)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def assert_fulltext_quality(spec: Dict[str, List[str]]) -> None:
    raw_html = fetch_arxiv_html(spec["id"])
    markdown = html_to_markdown(raw_html)
    assert spec["title_token"].lower() in markdown.lower(), f"标题缺失: {spec['title_token']}"

    doc = DocumentProcessor().process(spec["title_token"], markdown, source=f"arxiv-html:{spec['id']}", file_type="md")
    blocks = [block for block in doc.blocks if block.type != "heading"]
    block_types = [block.type for block in blocks]
    all_text = "\n".join(block.text for block in doc.blocks)

    assert len(doc.blocks) >= 25, f"block 数过少，疑似章节解析失败: {len(doc.blocks)}"
    for section in spec["required_sections"]:
        assert section in block_types, f"缺少章节 block: {section}, got={sorted(set(block_types))}"
    for term in spec["required_terms"]:
        assert term.lower() in all_text.lower(), f"全文 block 缺失关键术语: {term}"

    chunks = TypeAwareChunker(max_chars=2400, overlap=160).chunk(doc)
    chunk_types = [chunk.chunk_type for chunk in chunks]
    assert 10 <= len(chunks) <= 140, f"chunk 数异常: {len(chunks)}"
    for section in spec["required_sections"]:
        if section == "introduction":
            assert any(chunk.section_path.lower().endswith("introduction") for chunk in chunks), "缺少 introduction chunk"
        else:
            assert section in chunk_types, f"缺少 chunk 类型: {section}, got={sorted(set(chunk_types))}"
    assert len([chunk for chunk in chunks if chunk.chunk_type == "table"]) <= 20, "表格 chunk 过多，可能误解析正文为表格"
    contents = [chunk.content for chunk in chunks]
    assert len(contents) == len(set(contents)), "出现重复 chunk"

    print(
        f"[PASS] arXiv HTML 全文切分：{spec['title_token']} "
        f"blocks={len(doc.blocks)} chunks={len(chunks)} types={sorted(set(chunk_types))}"
    )


def main():
    for spec in FULLTEXT_PAPERS:
        assert_fulltext_quality(spec)
    print("\n=== arXiv HTML 全文抓取与章节切分严格测试通过 ===")


if __name__ == "__main__":
    main()
