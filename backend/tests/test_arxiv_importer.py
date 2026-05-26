"""
arXiv 导入服务回归测试。

验证目标：
1. arXiv ID / URL 能正确识别。
2. HTML 全文能转成结构化 Markdown。
3. 导入服务能回退摘要页并写入 chunk / 论文图。

运行方式：
    python backend/tests/test_arxiv_importer.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import DocumentChunk, Edge, get_session_factory, init_db
from services.arxiv_importer import ArxivImporter
from services.ingest import IngestService


class FakeLLM:
    provider = "fake"
    model = "fake-arxiv-importer"
    temperature = 0.0

    def embed(self, texts):
        return [[self._score(text, i) for i in range(16)] for text in texts]

    def complete_json(self, prompt, json_schema):
        return {"entities": [], "relations": []}

    def _score(self, text, index):
        return float((sum(ord(ch) for ch in text) + index * 29) % 101) / 101.0


ABS_HTML = """
<html><body>
<h1 class="title mathjax"><span>Title:</span> Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks</h1>
<div class="authors"><span>Authors:</span> Patrick Lewis, Ethan Perez et al.</div>
<blockquote class="abstract mathjax"><span>Abstract:</span> Retrieval-Augmented Generation combines a parametric generator with a non-parametric retriever for knowledge-intensive NLP tasks. The method improves open-domain question answering and generation by retrieving relevant passages from external memory. This abstract intentionally contains enough detail about RAG, retriever, generator, Natural Questions, and knowledge-intensive benchmarks for strict chunk validation.</blockquote>
<div class="dateline">[Submitted on 22 May 2020]</div>
<td class="tablecell comments mathjax">Accepted at NeurIPS 2020</td>
<td class="tablecell subjects">Computation and Language (cs.CL)</td>
</body></html>
"""

HTML_FULLTEXT = """
<html><head><title>Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks | arXiv</title></head>
<body><article>
<h1 class="ltx_title">Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks</h1>
<blockquote class="ltx_abstract">Abstract Retrieval-Augmented Generation combines a retriever and generator for knowledge-intensive NLP tasks.</blockquote>
<h2>1 Introduction</h2>
<p>RAG addresses knowledge-intensive natural language processing by retrieving passages and conditioning generation on evidence.</p>
<h2>2 Method</h2>
<p>Method: RAG. The retriever selects documents while the generator produces answers with retrieved context.</p>
<h2>3 Experiments</h2>
<p>Dataset: Natural Questions, TriviaQA. The evaluation reports Accuracy and F1 on open-domain question answering benchmarks.</p>
<table><tr><th>Model</th><th>Dataset</th><th>Metric</th></tr><tr><td>RAG</td><td>Natural Questions</td><td>F1</td></tr></table>
""" + "\n<p>RAG retriever generator Natural Questions evidence supports knowledge-intensive question answering experiments.</p>" * 12 + """
<h2>4 Conclusion</h2>
<p>Retrieval augmented generation improves knowledge-intensive tasks by combining retrieval with generation.</p>
<h2>References</h2>
<p>[1] Ashish Vaswani et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762</p>
</article></body></html>
"""


def fake_fetch(self, url):
    if "/abs/" in url:
        return ABS_HTML
    if "/html/" in url:
        return HTML_FULLTEXT
    raise AssertionError(f"unexpected url: {url}")


def doc_id_filter(items, doc_id):
    return [item for item in items if doc_id in (item.source_doc_ids or [])]


def main():
    init_db()
    db = get_session_factory()()
    created_doc_id = None
    try:
        importer = ArxivImporter(db)
        assert importer.extract_arxiv_id("2005.11401") == "2005.11401"
        assert importer.extract_arxiv_id("https://arxiv.org/abs/2005.11401") == "2005.11401"
        assert importer.extract_arxiv_id("https://arxiv.org/html/2005.11401v4") == "2005.11401"

        markdown = importer.html_to_markdown(HTML_FULLTEXT, fallback_title="RAG", min_length=500)
        assert "# Retrieval-Augmented Generation" in markdown
        assert "## Abstract" in markdown
        assert "## Method" in markdown or "# Method" in markdown
        assert "Natural Questions" in markdown

        with patch.object(ArxivImporter, "fetch", fake_fetch), patch("services.ingest.llm_manager", FakeLLM()):
            importer = ArxivImporter(db)
            result = importer.import_paper("https://arxiv.org/abs/2005.11401", prefer_html=True)
        created_doc_id = result["document_id"]
        assert result["arxiv_id"] == "2005.11401"
        assert result["imported_from"] == "html", result
        assert result["source"] == "arxiv-html:2005.11401", result

        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == created_doc_id).all()
        assert len(chunks) >= 5, f"chunk 数过少：{len(chunks)}"
        chunk_text = "\n".join(chunk.content for chunk in chunks)
        assert "【类型】abstract" in chunk_text
        assert "【类型】method" in chunk_text
        assert "【类型】experiment" in chunk_text
        assert "Natural Questions" in chunk_text

        edges = doc_id_filter(db.query(Edge).all(), created_doc_id)
        relations = {edge.relation for edge in edges}
        assert "PAPER_HAS_SECTION" in relations, relations
        assert "PAPER_CITES_PAPER" in relations, relations

        print("=== arXiv 导入服务回归测试通过 ===")
    finally:
        if created_doc_id:
            IngestService(db).delete_document(created_doc_id)
        db.close()


if __name__ == "__main__":
    main()
