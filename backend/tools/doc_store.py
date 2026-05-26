"""
DocStoreTool: 文档存储工具。
同时写入 MySQL 和 Chroma 向量库。
"""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from tools.base import BaseTool
from models.db import Document, DocumentChunk
from chroma.manager import chroma_manager
from llm.manager import llm_manager
from services.document_processor import DocumentProcessor, TypeAwareChunker


class DocStoreTool(BaseTool):
    """文档存储工具（MySQL + Chroma）"""

    name = "doc_store"
    description = "将文档存入 MySQL 和 Chroma 向量库"

    def __init__(self, db: Session, llm=None):
        self.db = db
        self.llm = llm if llm is not None else llm_manager

    def store_document(
        self,
        title: str,
        content: str,
        source: str = "manual",
        source_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """存储文档到 MySQL，并存入向量库"""
        doc = Document(
            title=title,
            content=content,
            source=source,
            source_url=source_url,
            tags=tags,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)

        # 同时写入 Chroma 向量库
        try:
            if self.llm:
                chunks = self._create_chunks(doc.id, content, title=title, source=source)
                embeddings = self.llm.embed([chunk.content for chunk in chunks]) if chunks else []
                for chunk, embedding in zip(chunks, embeddings or []):
                    metadata = getattr(chunk, "_chroma_metadata", None) or {
                        "kind": "doc_chunk",
                        "doc_id": doc.id,
                        "chunk_id": chunk.id,
                        "title": title,
                        "source": source,
                    }
                    metadata["chunk_id"] = chunk.id
                    chroma_manager.upsert(
                        doc_id=f"chunk:{chunk.id}",
                        text=chunk.content,
                        metadata=metadata,
                        embedding=embedding,
                    )
        except Exception:
            pass

        return {"id": doc.id, "title": doc.title, "created_at": doc.created_at.isoformat()}

    def _create_chunks(
        self,
        document_id: int,
        content: str,
        chunk_size: int = 1000,
        overlap: int = 120,
        title: str = "",
        source: str = "manual",
        file_type: Optional[str] = None,
    ) -> List[DocumentChunk]:
        try:
            parsed = DocumentProcessor().process(title or f"document-{document_id}", content, source=source, file_type=file_type)
            chunk_blocks = TypeAwareChunker(max_chars=chunk_size, overlap=overlap).chunk(parsed)
            if chunk_blocks:
                chunks = []
                for index, block in enumerate(chunk_blocks):
                    chunk = DocumentChunk(
                        document_id=document_id,
                        chunk_index=index,
                        content=block.content,
                        token_count=len(block.content),
                    )
                    self.db.add(chunk)
                    self.db.flush()
                    metadata = {
                        "kind": "doc_chunk",
                        "doc_id": document_id,
                        "chunk_id": chunk.id,
                        "title": title or parsed.title,
                        "source": source,
                        "chunk_type": block.chunk_type,
                        "file_type": parsed.file_type,
                        "section_path": block.section_path,
                        "page_start": block.page_start,
                        "page_end": block.page_end,
                    }
                    for key, value in block.metadata.items():
                        if value is not None and isinstance(value, (str, int, float, bool)):
                            metadata[key] = value
                    setattr(chunk, "_chroma_metadata", metadata)
                    chunks.append(chunk)
                self.db.commit()
                return chunks
        except Exception:
            self.db.rollback()

        text = content.strip()
        if not text:
            return []

        chunks = []
        start = 0
        index = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=index,
                    content=chunk_text,
                    token_count=len(chunk_text),
                )
                self.db.add(chunk)
                self.db.flush()
                setattr(chunk, "_chroma_metadata", {
                    "kind": "doc_chunk",
                    "doc_id": document_id,
                    "chunk_id": chunk.id,
                    "title": title,
                    "source": source,
                    "chunk_type": "paragraph",
                    "file_type": file_type or "text",
                    "section_path": "",
                })
                chunks.append(chunk)
                index += 1
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
        self.db.commit()
        return chunks

    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """获取文档详情"""
        doc = self.db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return None
        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "source": doc.source,
            "source_url": doc.source_url,
            "tags": doc.tags,
            "created_at": doc.created_at.isoformat(),
        }

    def delete_document(self, doc_id: int) -> bool:
        """删除文档（MySQL + Chroma）"""
        doc = self.db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return False
        chunks = self.db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        for chunk in chunks:
            chroma_manager.delete(f"chunk:{chunk.id}")
        self.db.delete(doc)
        self.db.commit()
        chroma_manager.delete(str(doc_id))
        return True

    def execute(self, **kwargs) -> Dict[str, Any]:
        """BaseTool 接口（代理到 store_document）"""
        action = kwargs.get("action", "store")
        if action == "store":
            return self.store_document(**kwargs)
        elif action == "delete":
            return {"deleted": self.delete_document(kwargs.get("doc_id"))}
        elif action == "get":
            return self.get_document(kwargs.get("doc_id"))
        return {"error": f"Unknown action: {action}"}
