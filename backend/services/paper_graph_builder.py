"""
论文结构图构建服务。

把论文文档、章节、chunk、方法、数据集和指标写入现有 Node/Edge 表，
让 GraphRetrievalService 后续可以检索论文结构与实验关系。
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from sqlalchemy.orm import Session

from models.db import Document, DocumentChunk, Edge, Node
from services.document_processor.reference_parser import ParsedReference, ReferenceParser


class PaperGraphBuilder:
    """基于结构化 DocumentChunk 构建轻量论文图。"""

    STRUCTURAL_CHUNK_TYPES = {"table", "code", "equation", "reference"}

    def __init__(self, db: Session):
        self.db = db
        self.reference_parser = ReferenceParser()

    def build_for_document(self, document_id: int) -> Dict[str, Any]:
        doc = self.db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            return {"nodes_created": 0, "edges_created": 0, "message": "文档不存在"}

        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            return {"nodes_created": 0, "edges_created": 0, "message": "文档暂无 chunk"}

        before_nodes = self.db.query(Node).count()
        before_edges = self.db.query(Edge).count()

        paper_title = self._paper_title(doc, chunks)
        paper_node = self._get_or_create_node(
            name=paper_title,
            type_="paper",
            description=f"论文：{paper_title}",
            doc_id=document_id,
            properties={"document_id": document_id, "source": doc.source},
        )

        section_nodes: Dict[str, Node] = {}
        chunk_nodes: List[Node] = []
        previous_chunk_node: Optional[Node] = None

        for chunk in chunks:
            metadata = self._extract_chunk_metadata(chunk.content)
            section_path = metadata.get("section_path") or "正文"
            chunk_type = metadata.get("chunk_type") or "paragraph"

            section_node = self._ensure_section_path(
                paper_node=paper_node,
                section_nodes=section_nodes,
                section_path=section_path,
                document_id=document_id,
            )
            chunk_node = self._get_or_create_node(
                name=f"{paper_title}#chunk-{chunk.chunk_index}",
                type_="chunk",
                description=self._shorten(chunk.content, 180),
                doc_id=document_id,
                properties={
                    "document_id": document_id,
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "chunk_type": chunk_type,
                    "section_path": section_path,
                },
            )
            chunk_nodes.append(chunk_node)

            self._ensure_edge(section_node, chunk_node, "SECTION_HAS_CHUNK", document_id)
            if previous_chunk_node:
                self._ensure_edge(previous_chunk_node, chunk_node, "NEXT_CHUNK", document_id)
                self._ensure_edge(chunk_node, previous_chunk_node, "PREV_CHUNK", document_id)
            previous_chunk_node = chunk_node

            if chunk_type in self.STRUCTURAL_CHUNK_TYPES:
                typed_node = self._get_or_create_node(
                    name=f"{paper_title}#{chunk_type}-{chunk.chunk_index}",
                    type_=chunk_type,
                    description=self._shorten(chunk.content, 160),
                    doc_id=document_id,
                    properties={
                        "document_id": document_id,
                        "chunk_id": chunk.id,
                        "chunk_type": chunk_type,
                        "section_path": section_path,
                    },
                )
                self._ensure_edge(section_node, typed_node, f"SECTION_HAS_{chunk_type.upper()}", document_id)
                self._ensure_edge(typed_node, chunk_node, "SECTION_HAS_CHUNK", document_id)
                if chunk_type == "reference":
                    self._build_citation_edges(paper_node, section_node, chunk_node, chunk.content, document_id)

            self._build_method_experiment_edges(paper_node, chunk_node, chunk.content, metadata, document_id)

        self.db.commit()
        return {
            "nodes_created": self.db.query(Node).count() - before_nodes,
            "edges_created": self.db.query(Edge).count() - before_edges,
            "paper_node_id": paper_node.id,
            "chunk_nodes": len(chunk_nodes),
            "message": "论文结构图构建完成",
        }

    def _ensure_section_path(
        self,
        paper_node: Node,
        section_nodes: Dict[str, Node],
        section_path: str,
        document_id: int,
    ) -> Node:
        parts = [part.strip() for part in section_path.split("/") if part.strip()] or ["正文"]
        parent = paper_node
        current_path = ""
        current_node = paper_node
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            if current_path not in section_nodes:
                section_nodes[current_path] = self._get_or_create_node(
                    name=f"{paper_node.name}#{current_path}",
                    type_="section",
                    description=f"论文《{paper_node.name}》章节：{current_path}",
                    doc_id=document_id,
                    properties={"document_id": document_id, "section_path": current_path},
                )
            current_node = section_nodes[current_path]
            relation = "PAPER_HAS_SECTION" if parent.id == paper_node.id else "CHILD_SECTION"
            self._ensure_edge(parent, current_node, relation, document_id)
            if parent.id != paper_node.id:
                self._ensure_edge(current_node, parent, "PARENT_SECTION", document_id)
            parent = current_node
        return current_node

    def _build_method_experiment_edges(
        self,
        paper_node: Node,
        chunk_node: Node,
        content: str,
        metadata: Dict[str, str],
        document_id: int,
    ) -> None:
        method_names = self._split_values(metadata.get("method_name")) or self._extract_methods(content)
        datasets = self._split_values(metadata.get("dataset")) or self._extract_labeled_values(content, "数据集")
        metrics = self._split_values(metadata.get("metric")) or self._extract_labeled_values(content, "指标")

        method_nodes = []
        for method in method_names[:5]:
            method_node = self._get_or_create_node(
                name=method,
                type_="method",
                description=f"论文《{paper_node.name}》中的方法：{method}",
                doc_id=document_id,
                properties={"document_id": document_id, "paper_title": paper_node.name},
            )
            method_nodes.append(method_node)
            self._ensure_edge(paper_node, method_node, "PAPER_HAS_METHOD", document_id)
            self._ensure_edge(method_node, chunk_node, "SECTION_HAS_CHUNK", document_id)

        for dataset in datasets[:8]:
            dataset_node = self._get_or_create_node(
                name=dataset,
                type_="dataset",
                description=f"实验数据集：{dataset}",
                doc_id=document_id,
                properties={"document_id": document_id},
            )
            for method_node in method_nodes or [paper_node]:
                self._ensure_edge(method_node, dataset_node, "METHOD_EVALUATED_ON_DATASET", document_id)
            self._ensure_edge(dataset_node, chunk_node, "SECTION_HAS_CHUNK", document_id)

        for metric in metrics[:8]:
            metric_node = self._get_or_create_node(
                name=metric,
                type_="metric",
                description=f"实验指标：{metric}",
                doc_id=document_id,
                properties={"document_id": document_id},
            )
            for method_node in method_nodes or [paper_node]:
                self._ensure_edge(method_node, metric_node, "METHOD_REPORTED_METRIC", document_id)
            self._ensure_edge(metric_node, chunk_node, "SECTION_HAS_CHUNK", document_id)

    def _build_citation_edges(
        self,
        paper_node: Node,
        section_node: Node,
        chunk_node: Node,
        content: str,
        document_id: int,
    ) -> None:
        references = self.reference_parser.parse(content)
        for reference in references[:80]:
            reference_node = self._get_or_create_node(
                name=self._reference_node_name(reference),
                type_="reference",
                description=reference.raw_text,
                doc_id=document_id,
                properties={
                    "document_id": document_id,
                    "citation_key": reference.citation_key,
                    "title": reference.title,
                    "authors": reference.authors,
                    "year": reference.year,
                    "venue": reference.venue,
                    "doi": reference.doi,
                    "arxiv_id": reference.arxiv_id,
                    "raw_text": reference.raw_text,
                },
            )
            cited_paper_node = self._get_or_create_node(
                name=self._cited_paper_name(reference),
                type_="paper",
                description=f"被论文《{paper_node.name}》引用的论文：{reference.raw_text}",
                doc_id=document_id,
                properties={
                    "document_id": document_id,
                    "citation_key": reference.citation_key,
                    "title": reference.title,
                    "authors": reference.authors,
                    "year": reference.year,
                    "venue": reference.venue,
                    "doi": reference.doi,
                    "arxiv_id": reference.arxiv_id,
                    "is_cited_reference": True,
                },
            )
            self._ensure_edge(paper_node, cited_paper_node, "PAPER_CITES_PAPER", document_id)
            self._ensure_edge(section_node, reference_node, "SECTION_MENTIONS_REFERENCE", document_id)
            self._ensure_edge(chunk_node, reference_node, "CHUNK_MENTIONS_REFERENCE", document_id)
            self._ensure_edge(reference_node, cited_paper_node, "REFERENCE_RESOLVES_TO_PAPER", document_id)

    def _reference_node_name(self, reference: ParsedReference) -> str:
        if reference.citation_key:
            return f"reference:{reference.citation_key}:{reference.title or reference.raw_text}"[:255]
        return f"reference:{reference.title or reference.raw_text}"[:255]

    def _cited_paper_name(self, reference: ParsedReference) -> str:
        if reference.title:
            return reference.title[:255]
        if reference.arxiv_id:
            return f"arXiv:{reference.arxiv_id}"
        return reference.raw_text[:255]

    def _paper_title(self, doc: Document, chunks: Iterable[DocumentChunk]) -> str:
        for chunk in chunks:
            metadata = self._extract_chunk_metadata(chunk.content)
            if metadata.get("paper_title"):
                return metadata["paper_title"]
        return doc.title

    def _get_or_create_node(
        self,
        name: str,
        type_: str,
        description: str,
        doc_id: int,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Node:
        node = (
            self.db.query(Node)
            .filter(Node.name == name, Node.type == type_)
            .first()
        )
        if node:
            node.source_doc_ids = self._merge_doc_ids(node.source_doc_ids, doc_id)
            merged_properties = dict(node.properties or {})
            merged_properties.update(properties or {})
            node.properties = merged_properties
            if description and not node.description:
                node.description = description
            return node

        node = Node(
            name=name[:255],
            type=type_,
            description=description,
            source_doc_ids=[doc_id],
            properties=properties or {},
            confidence=0.85,
        )
        self.db.add(node)
        self.db.flush()
        return node

    def _ensure_edge(self, source: Node, target: Node, relation: str, doc_id: int) -> Edge:
        edge = (
            self.db.query(Edge)
            .filter(Edge.source_id == source.id, Edge.target_id == target.id, Edge.relation == relation)
            .first()
        )
        if edge:
            edge.source_doc_ids = self._merge_doc_ids(edge.source_doc_ids, doc_id)
            return edge
        edge = Edge(
            source_id=source.id,
            target_id=target.id,
            relation=relation,
            type="paper_structure",
            confidence=0.85,
            source_doc_ids=[doc_id],
        )
        self.db.add(edge)
        self.db.flush()
        return edge

    def _extract_chunk_metadata(self, content: str) -> Dict[str, str]:
        labels = {
            "chunk_type": "类型",
            "section_path": "章节",
            "paper_title": "论文",
            "method_name": "方法",
            "metric": "指标",
            "dataset": "数据集",
        }
        metadata = {}
        for key, label in labels.items():
            match = re.search(rf"^【{label}】(.+)$", content or "", re.M)
            if match:
                value = match.group(1).strip()
                if value:
                    metadata[key] = value
        return metadata

    def _extract_labeled_values(self, content: str, label: str) -> List[str]:
        match = re.search(rf"^【{label}】(.+)$", content or "", re.M)
        if not match:
            return []
        return self._split_values(match.group(1))

    def _extract_methods(self, content: str) -> List[str]:
        methods = []
        for pattern in [r"^Method:\s*([^\n]+)", r"^方法[:：]\s*([^\n]+)"]:
            for match in re.finditer(pattern, content or "", re.M | re.I):
                methods.extend(self._split_values(match.group(1)))
        return methods

    def _split_values(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        cleaned = value.strip()
        if not cleaned or cleaned.upper() == "N/A":
            return []
        parts = re.split(r"[,，、;/；]|\band\b|\s+和\s+", cleaned, flags=re.I)
        values = []
        for part in parts:
            item = part.strip(" .。:：")
            if item and item.upper() != "N/A" and item not in values:
                values.append(item[:255])
        return values

    def _merge_doc_ids(self, existing: Optional[List[int]], doc_id: int) -> List[int]:
        ids = list(existing or [])
        if doc_id not in ids:
            ids.append(doc_id)
        return ids

    def _shorten(self, text: str, limit: int) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return cleaned[:limit]
