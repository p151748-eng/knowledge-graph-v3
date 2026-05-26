"""
定向抓取公开 AI/RAG 文档并导入本地 RAG 库。

运行方式：
    python backend/crawl_ai_docs.py
"""

import html.parser
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.db import Document, DocumentChunk, get_session_factory, init_db
from services.ingest import IngestService


@dataclass
class CrawlTarget:
    title: str
    url: str
    tags: List[str]


TARGETS = [
    CrawlTarget(
        title="LangChain RAG 与检索文档",
        url="https://docs.langchain.com/oss/python/langchain/retrieval",
        tags=["ai", "rag", "langchain", "retrieval", "crawler"],
    ),
    CrawlTarget(
        title="LangChain Agents 文档",
        url="https://docs.langchain.com/oss/python/langchain/agents",
        tags=["ai", "agent", "langchain", "crawler"],
    ),
    CrawlTarget(
        title="LlamaIndex RAG 文档",
        url="https://docs.llamaindex.ai/en/stable/understanding/rag/",
        tags=["ai", "rag", "llamaindex", "crawler"],
    ),
    CrawlTarget(
        title="LlamaIndex Knowledge Graph Index 文档",
        url="https://docs.llamaindex.ai/en/stable/examples/index_structs/knowledge_graph/KnowledgeGraphDemo/",
        tags=["ai", "knowledge-graph", "llamaindex", "crawler"],
    ),
    CrawlTarget(
        title="Pinecone RAG 教程",
        url="https://www.pinecone.io/learn/retrieval-augmented-generation/",
        tags=["ai", "rag", "vector-database", "pinecone", "crawler"],
    ),
    CrawlTarget(
        title="Pinecone Vector Database 教程",
        url="https://www.pinecone.io/learn/vector-database/",
        tags=["ai", "embedding", "vector-database", "pinecone", "crawler"],
    ),
    CrawlTarget(
        title="Pinecone Rerankers 教程",
        url="https://www.pinecone.io/learn/series/rag/rerankers/",
        tags=["ai", "rag", "rerank", "retrieval", "pinecone", "crawler"],
    ),
    CrawlTarget(
        title="Pinecone Hybrid Search 教程",
        url="https://www.pinecone.io/learn/hybrid-search/",
        tags=["ai", "hybrid-search", "bm25", "vector", "pinecone", "crawler"],
    ),
    CrawlTarget(
        title="Cohere Rerank 文档",
        url="https://docs.cohere.com/docs/rerank-overview",
        tags=["ai", "rerank", "retrieval", "cohere", "crawler"],
    ),
    CrawlTarget(
        title="Hugging Face Transformers Tasks 文档",
        url="https://huggingface.co/docs/transformers/tasks/sequence_classification",
        tags=["ai", "transformers", "nlp", "fine-tuning", "huggingface", "crawler"],
    ),
    CrawlTarget(
        title="Hugging Face Text Generation 文档",
        url="https://huggingface.co/docs/transformers/llm_tutorial",
        tags=["ai", "llm", "text-generation", "huggingface", "crawler"],
    ),
    CrawlTarget(
        title="PyTorch Neural Networks 教程",
        url="https://docs.pytorch.org/tutorials/beginner/blitz/neural_networks_tutorial.html",
        tags=["ai", "deep-learning", "neural-network", "pytorch", "crawler"],
    ),
    CrawlTarget(
        title="OpenAI Embeddings 指南",
        url="https://platform.openai.com/docs/guides/embeddings",
        tags=["ai", "embedding", "openai", "crawler"],
    ),
    CrawlTarget(
        title="OpenAI Text Generation 指南",
        url="https://platform.openai.com/docs/guides/text-generation",
        tags=["ai", "llm", "openai", "crawler"],
    ),
]


class TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip_depth = 0
        self.current_href = ""
        self.parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            level = int(tag[1])
            self.parts.append("\n" + "#" * level + " ")
        elif tag in {"p", "div", "section", "article", "li", "tr", "pre", "blockquote"}:
            self.parts.append("\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self.current_href = attrs_dict.get("href", "")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "a":
            self.current_href = ""
        if not self.skip_depth and tag in {"h1", "h2", "h3", "h4", "p", "li", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text + " ")

    def text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = []
        seen = set()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                if lines and lines[-1]:
                    lines.append("")
                continue
            if len(line) < 3:
                continue
            if line in seen and len(line) < 120:
                continue
            seen.add(line)
            lines.append(line)
        return "\n".join(lines).strip()


def fetch_text(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 kg-agent-doc-crawler/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        html = resp.read().decode(charset, errors="ignore")
    parser = TextExtractor()
    parser.feed(html)
    return parser.text()


def normalize_content(target: CrawlTarget, text: str) -> str:
    source_line = f"原始来源：{target.url}"
    content = f"# {target.title}\n\n{source_line}\n\n{text}"
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content


def main():
    init_db()
    db = get_session_factory()()
    try:
        service = IngestService(db)
        imported = []
        for target in TARGETS:
            print(f"[抓取] {target.title} {target.url}")
            try:
                text = fetch_text(target.url)
                content = normalize_content(target, text)
                if len(content) < 1200:
                    print(f"[跳过] 文本量不足 chars={len(content)}")
                    continue

                existing = (
                    db.query(Document)
                    .filter(Document.source == "web_crawl_ai_docs", Document.title == target.title)
                    .first()
                )
                if existing:
                    service.delete_document(existing.id)

                result = service.ingest_text(
                    title=target.title,
                    content=content,
                    source="web_crawl_ai_docs",
                    tags=target.tags,
                )
                doc_id = result["document_id"]
                chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
                imported.append((target.title, doc_id, len(content), chunks, result["nodes_created"], result["edges_created"]))
                print(f"[导入] doc_id={doc_id} chars={len(content)} chunks={chunks}")
                time.sleep(1)
            except Exception as exc:
                print(f"[失败] {target.title}: {exc}")

        print("\n=== 导入结果 ===")
        print(f"导入文档数：{len(imported)}")
        print(f"总字符数：{sum(item[2] for item in imported)}")
        print(f"总分片数：{sum(item[3] for item in imported)}")
        for title, doc_id, chars, chunks, nodes, edges in imported:
            print(f"- {title}: doc_id={doc_id}, chars={chars}, chunks={chunks}, nodes={nodes}, edges={edges}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
