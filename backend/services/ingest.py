"""
IngestService: 文档导入服务。
从文本/文件中抽取实体，构建知识图谱。
"""

import re
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from models.db import Node, Edge, Document, DocumentChunk
from sqlalchemy import or_
from tools.kg_extract import KGExtractTool
from tools.doc_store import DocStoreTool
from llm.manager import llm_manager
from chroma.manager import chroma_manager
from services.document_processor import DocumentProcessor, TypeAwareChunker
from services.paper_graph_builder import PaperGraphBuilder


class IngestService:
    """文档导入服务"""

    def __init__(self, db: Session):
        self.db = db
        self.kg_extract = KGExtractTool(db, llm_manager)
        self.doc_store = DocStoreTool(db, llm_manager)

    def ingest_text(
        self,
        title: str,
        content: str,
        source: str = "manual",
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        导入文本内容，自动抽取实体构建 KG。

        返回:
        {
            "document_id": int,
            "nodes_created": int,
            "edges_created": int,
            "entities_extracted": [...],
        }
        """
        nodes_created = 0
        edges_created = 0

        # 1. 先存储文档（不含向量，后续补）
        doc = Document(
            title=title,
            content=content,
            source=source,
            tags=tags,
        )
        self.db.add(doc)
        self.db.flush()

        # 2. 实体抽取（使用 mock 或 LLM）
        extracted = self._extract_entities(content)
        entities = extracted.get("entities", [])
        relations = extracted.get("relations", [])

        # 3. 存储节点
        existing_names = {n.name for n in self.db.query(Node.name).all()}
        node_id_map = {}
        entity_list = []

        for entity in entities:
            name = entity.get("name", "").strip()
            if not name or name in existing_names:
                continue

            node = Node(
                name=name,
                type=entity.get("type", "entity"),
                description=entity.get("description", ""),
                source_doc_ids=[doc.id],
                confidence=0.7,
            )
            self.db.add(node)
            self.db.flush()
            self.db.refresh(node)
            node_id_map[name] = node.id
            entity_list.append({"name": name, "type": entity.get("type", "entity")})
            existing_names.add(name)
            nodes_created += 1

        # 4. 存储关系
        for rel in relations:
            src_name = rel.get("source", "").strip()
            tgt_name = rel.get("target", "").strip()
            rel_type = rel.get("relation", "相关")

            src_id = node_id_map.get(src_name)
            tgt_id = node_id_map.get(tgt_name)

            if src_id and tgt_id and src_id != tgt_id:
                existing_edge = (
                    self.db.query(Edge)
                    .filter(
                        Edge.source_id == src_id,
                        Edge.target_id == tgt_id,
                        Edge.relation == rel_type,
                    )
                    .first()
                )
                if not existing_edge:
                    edge = Edge(
                        source_id=src_id,
                        target_id=tgt_id,
                        relation=rel_type,
                        confidence=0.7,
                        source_doc_ids=[doc.id],
                    )
                    self.db.add(edge)
                    edges_created += 1

        self.db.commit()

        # 5. 存入分片和向量库
        try:
            chunks = self._create_chunks(doc.id, content, title=title, source=source)
            if chunks:
                embeddings = llm_manager.embed([chunk.content for chunk in chunks])
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

        try:
            graph_result = PaperGraphBuilder(self.db).build_for_document(doc.id)
            nodes_created += graph_result.get("nodes_created", 0)
            edges_created += graph_result.get("edges_created", 0)
        except Exception:
            pass

        return {
            "document_id": doc.id,
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "entities_extracted": entity_list,
            "message": f"文档导入成功，创建了 {nodes_created} 个节点和 {edges_created} 个关系",
        }

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
        """创建文档分片并写入数据库。"""
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

    def _extract_entities(self, text: str) -> Dict[str, Any]:
        """
        从文本中抽取实体。
        优先使用 LLM，失败则用 mock 关键词提取。
        """
        try:
            result = self.kg_extract.execute(text)
            if result and result.get("entities"):
                return result
        except Exception:
            pass

        # Fallback: 从文本中提取中文词组作为 mock 实体
        words = re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]{2,}", text)
        word_freq: Dict[str, int] = {}
        for w in words:
            if len(w) >= 2:
                word_freq[w] = word_freq.get(w, 0) + 1

        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        entities = [
            {"name": w[0], "type": "concept", "description": ""}
            for w in top_words if w[1] > 1
        ]
        return {"entities": entities, "relations": []}

    def list_documents(
        self,
        search: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        """获取文档列表"""
        query = self.db.query(Document)
        if search:
            query = query.filter(
                or_(Document.title.ilike(f"%{search}%"), Document.content.ilike(f"%{search}%"))
            )
        if source:
            query = query.filter(Document.source == source)

        total = query.count()
        docs = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
        return docs, total

    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """获取文档详情"""
        doc = self.db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return None

        # 获取关联节点
        related_nodes = (
            self.db.query(Node)
            .filter(Node.source_doc_ids.contains([doc_id]))
            .all()
        )

        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "source": doc.source,
            "source_url": doc.source_url,
            "tags": doc.tags,
            "related_nodes": [
                {"id": n.id, "name": n.name}
                for n in related_nodes
            ],
            "created_at": doc.created_at.isoformat(),
        }

    def delete_document(self, doc_id: int) -> bool:
        """删除文档"""
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
