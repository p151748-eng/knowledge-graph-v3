"""
BM25SearchTool: 基于 DocumentChunk 的轻量 BM25 检索。
"""

import math
import re
from collections import Counter
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from models.db import Document, DocumentChunk
from services.query_router import extract_keywords
from tools.base import BaseTool


class BM25SearchTool(BaseTool):
    """文档分片 BM25 检索工具"""

    name = "bm25_search"
    description = "基于文档分片执行轻量 BM25 检索"

    def __init__(self, db: Session):
        self.db = db

    def execute(self, query: str, top_k: int = 10, query_source: str = "original", **kwargs) -> List[Dict[str, Any]]:
        terms = self._tokenize(query)
        if not terms:
            terms = extract_keywords(query)
        if not terms:
            return []

        chunks = (
            self.db.query(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.source != "query_template")
            .all()
        )
        if not chunks:
            return []

        total_docs = len(chunks)
        avg_len = sum(max(1, chunk.token_count or len(chunk.content)) for chunk, _ in chunks) / total_docs
        doc_freq = Counter()
        tokenized_chunks = []

        for chunk, doc in chunks:
            tokens = self._tokenize(chunk.content)
            token_set = set(tokens)
            for term in set(terms):
                if term in token_set:
                    doc_freq[term] += 1
            tokenized_chunks.append((chunk, doc, tokens))

        min_should_match = 1 if kwargs.get("allow_partial_match", True) else len(set(terms))
        scored = []
        k1 = 1.5
        b = 0.75
        for chunk, doc, tokens in tokenized_chunks:
            tf = Counter(tokens)
            doc_len = max(1, chunk.token_count or len(chunk.content))
            score = 0.0
            matched_terms = 0
            for term in terms:
                freq = tf.get(term, 0)
                if freq <= 0:
                    continue
                matched_terms += 1
                idf = math.log(1 + (total_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                denom = freq + k1 * (1 - b + b * doc_len / avg_len)
                score += idf * (freq * (k1 + 1)) / denom
            if score > 0 and matched_terms >= min_should_match:
                scored.append({
                    "id": chunk.id,
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "title": doc.title,
                    "content": chunk.content,
                    "score": score,
                    "match_type": "bm25",
                    "result_type": "chunk",
                    "query_source": query_source,
                    "source": doc.source,
                    **self._extract_chunk_metadata(chunk.content),
                })

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _extract_chunk_metadata(self, content: str) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        labels = {
            "chunk_type": "类型",
            "section_path": "章节",
            "paper_title": "论文",
            "authors": "作者",
            "year": "年份",
            "method_name": "方法",
            "metric": "指标",
            "dataset": "数据集",
        }
        for key, label in labels.items():
            match = re.search(rf"^【{label}】(.+)$", content or "", re.M)
            if match:
                value = match.group(1).strip()
                if value:
                    metadata[key] = value
        return metadata

    def _tokenize(self, text: str) -> List[str]:
        tokens = []
        tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9_]*", text.lower()))
        tokens.extend(re.findall(r"[一-龥]{2,6}", text))
        tokens.extend(re.findall(r"\d+", text))
        return tokens
