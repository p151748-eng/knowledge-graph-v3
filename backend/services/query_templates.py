"""
QueryTemplateService: 提问补全模板库。
第一版复用 Document + Chroma，不单独建表。
"""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from chroma.manager import chroma_manager
from models.db import Document, get_session_factory


DEFAULT_QUERY_TEMPLATES = [
    {
        "name": "事实解释模板",
        "intent": "fact",
        "patterns": ["X 是什么？", "介绍一下 X", "X 的定义是什么？"],
        "rewrite_template": "解释 {entity} 的定义、作用和相关证据。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "ego"},
    },
    {
        "name": "原理说明模板",
        "intent": "explain",
        "patterns": ["X 为什么这样设计？", "X 的原理是什么？", "X 的机制是什么？"],
        "rewrite_template": "说明 {entity} 的工作原理、设计原因和关键机制。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "ego"},
    },
    {
        "name": "关系分析模板",
        "intent": "relation",
        "patterns": ["A 和 B 有什么关系？", "A 怎么影响 B？", "A 和 B 怎么配合？"],
        "rewrite_template": "分析 {entity_a} 与 {entity_b} 的关系、连接路径、共同上下文和证据来源。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "path"},
    },
    {
        "name": "路径推理模板",
        "intent": "path",
        "patterns": ["A 如何导致 B？", "A 到 B 的链路是什么？", "为什么 A 会影响 B？"],
        "rewrite_template": "查找 {entity_a} 到 {entity_b} 的多跳路径、因果链路和中间节点。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "path"},
    },
    {
        "name": "子图梳理模板",
        "intent": "subgraph",
        "patterns": ["围绕 X 有哪些模块？", "X 的上下游有哪些？", "梳理 X 的局部结构。"],
        "rewrite_template": "围绕 {topic} 梳理相关节点、上下游关系和局部结构。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "subgraph"},
    },
    {
        "name": "全局总结模板",
        "intent": "global_summary",
        "patterns": ["整体架构是什么？", "主要主题有哪些？", "全局总结一下。"],
        "rewrite_template": "总结知识库或系统的整体主题、模块分类和高层结构。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": False, "graph_method": "none"},
    },
    {
        "name": "对比分析模板",
        "intent": "compare",
        "patterns": ["A 和 B 有什么区别？", "A 和 B 对比一下", "A 相比 B 的优缺点是什么？"],
        "rewrite_template": "对比 {entity_a} 与 {entity_b} 的定义、使用场景、优缺点和关系。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "path"},
    },
    {
        "name": "优化建议模板",
        "intent": "optimize",
        "patterns": ["X 怎么优化？", "X 哪里不合理？", "如何改进 X？"],
        "rewrite_template": "分析 {topic} 的现状、问题、优化方向和可执行改进步骤。",
        "retrieval_plan": {"bm25": True, "vector": True, "graph": True, "graph_method": "subgraph"},
    },
]


class QueryTemplateService:
    """提问补全模板服务"""

    def __init__(self, db: Optional[Session] = None, llm: Any = None):
        self.db = db
        self.llm = llm

    def ensure_default_templates(self) -> int:
        """初始化默认模板，返回新增数量。"""
        db = self.db or get_session_factory()()
        close_db = self.db is None
        created = 0
        try:
            if self.llm is None:
                from llm.manager import llm_manager
                self.llm = llm_manager

            for template in DEFAULT_QUERY_TEMPLATES:
                exists = (
                    db.query(Document)
                    .filter(Document.source == "query_template", Document.title == template["name"])
                    .first()
                )
                if exists:
                    continue

                content = self._template_to_text(template)
                doc = Document(
                    title=template["name"],
                    content=content,
                    source="query_template",
                    tags=["template", template["intent"]],
                )
                db.add(doc)
                db.flush()

                embeddings = self.llm.embed([content]) if self.llm else []
                if embeddings:
                    chroma_manager.upsert(
                        doc_id=f"template:{doc.id}",
                        text=content,
                        metadata={
                            "kind": "query_template",
                            "doc_id": doc.id,
                            "intent": template["intent"],
                            "name": template["name"],
                        },
                        embedding=embeddings[0],
                    )
                created += 1

            db.commit()
            return created
        except Exception:
            db.rollback()
            return created
        finally:
            if close_db:
                db.close()

    def retrieve_templates(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """检索与用户问题相似的模板。"""
        if self.llm is None:
            from llm.manager import llm_manager
            self.llm = llm_manager

        embeddings = self.llm.embed([query]) if self.llm else []
        if not embeddings:
            return []

        hits = chroma_manager.query(embeddings[0], top_k=top_k, where={"kind": "query_template"})
        templates = []
        for hit in hits:
            metadata = hit.get("metadata") or {}
            templates.append({
                "name": metadata.get("name", ""),
                "intent": metadata.get("intent", ""),
                "content": hit.get("text", ""),
                "score": hit.get("score", 0.0),
            })
        return templates

    def _template_to_text(self, template: Dict[str, Any]) -> str:
        return json.dumps(template, ensure_ascii=False, indent=2)
