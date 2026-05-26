"""
HybridSearchTool: RAG + KG 混合检索工具。
按 Query Router 计划执行 BM25 + Vector + Graph，并保留旧返回字段兼容上层。
"""

import re
from typing import Any, Dict, List, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session

from chroma.manager import chroma_manager
from models.db import Document, DocumentChunk, Node
from services.graph_retrieval import GraphRetrievalService
from services.query_router import RetrievalPlan, route_query
from tools.base import BaseTool
from tools.bm25_search import BM25SearchTool
from observability.langsmith_tracing import traceable


class HybridSearchTool(BaseTool):
    """混合检索工具：BM25 + 向量 + 图检索"""

    name = "hybrid_search"
    description = "执行 BM25、向量、图检索三路混合检索"

    def __init__(self, db: Session, embedding_service: Any = None):
        self.db = db
        self.embedding_service = embedding_service

    @traceable(name="hybrid_search.execute", run_type="retriever")
    def execute(
        self,
        query: str,
        top_k: int = 10,
        context: str = "",
        use_llm_router: bool = True,
        plan_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = route_query(query, context=context, use_llm=use_llm_router, llm=self.embedding_service)
        plan = self._apply_plan_override(plan, plan_override)
        main_query = plan.optimized_query or query
        override_expanded = []
        if plan_override and isinstance(plan_override.get("expanded_queries"), list):
            override_expanded = [str(q) for q in plan_override.get("expanded_queries", []) if str(q).strip()]
        queries = [main_query] + [q for q in plan.expanded_queries + override_expanded if q and q != main_query]

        results = {
            "keyword_hits": [],
            "bm25_hits": [],
            "semantic_hits": [],
            "entity_hits": [],
            "graph_hits": [],
            "merged": [],
            "context_text": "",
            "plan": plan.to_dict(),
            "optimized_query": main_query,
            "expanded_queries": plan.expanded_queries,
        }

        if plan.bm25:
            allow_partial_match = not bool(plan_override and plan_override.get("strict_bm25_terms"))
            results["bm25_hits"] = self._bm25_search(queries, plan.bm25_top_k, allow_partial_match=allow_partial_match)

        if plan.vector:
            results["semantic_hits"] = self._semantic_search(main_query, plan.vector_top_k)

        results["entity_hits"] = self._entity_search(plan.entities + [query], limit=max(top_k, plan.graph_top_k or 5))
        results["keyword_hits"] = results["entity_hits"]

        seed_ids = [hit["id"] for hit in results["entity_hits"] if hit.get("result_type") == "node"]
        if plan.graph:
            results["graph_hits"] = GraphRetrievalService(self.db).search(
                plan.graph_method,
                plan.entities,
                seed_ids,
                main_query,
                limit=plan.graph_top_k or top_k,
                depth=plan.graph_depth,
            )

        results["merged"] = self._merge_and_rank(results, plan, top_k, main_query)
        results["context_text"] = self._build_context_text(query, main_query, plan, results)
        return results

    def _apply_plan_override(self, plan: RetrievalPlan, override: Optional[Dict[str, Any]]) -> RetrievalPlan:
        if not override:
            return plan
        allowed_bool = {"bm25", "vector", "graph", "community"}
        allowed_int = {"bm25_top_k", "vector_top_k", "graph_top_k", "graph_depth"}
        for key in allowed_bool:
            if key in override:
                setattr(plan, key, bool(override[key]))
        for key in allowed_int:
            if key in override:
                try:
                    setattr(plan, key, max(1, min(20, int(override[key]))))
                except Exception:
                    pass
        if override.get("graph_method") in {"none", "ego", "path", "subgraph"}:
            plan.graph_method = override["graph_method"]
        if isinstance(override.get("optimized_query"), str) and override["optimized_query"].strip():
            plan.optimized_query = override["optimized_query"].strip()
        if isinstance(override.get("expanded_queries"), list):
            plan.expanded_queries = [str(q) for q in override["expanded_queries"] if str(q).strip()][:3]
        if isinstance(override.get("entities"), list):
            plan.entities = [str(e) for e in override["entities"] if str(e).strip()][:8]
        if isinstance(override.get("intent"), str) and override["intent"].strip():
            plan.intent = override["intent"].strip()
            plan.query_type = plan.intent
        if isinstance(override.get("preferred_chunk_types"), list):
            plan.preferred_chunk_types = [str(t) for t in override["preferred_chunk_types"] if str(t).strip()][:8]
        plan.reason = f"{plan.reason}; CRAG override" if plan.reason else "CRAG override"
        return plan

    def _bm25_search(self, queries: List[str], limit: int, allow_partial_match: bool = True) -> List[Dict[str, Any]]:
        tool = BM25SearchTool(self.db)
        hits = []
        for index, query in enumerate(queries):
            query_source = "optimized" if index == 0 else f"expanded_{index}"
            hits.extend(tool.execute(query, top_k=limit, query_source=query_source, allow_partial_match=allow_partial_match))
        return self._dedupe_hits(hits, key_prefix="chunk")[:limit]

    def _semantic_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """向量语义检索，返回文档分片或兼容旧文档命中。"""
        try:
            if not self.embedding_service:
                from llm.manager import llm_manager
                self.embedding_service = llm_manager
            embeddings = self.embedding_service.embed([query])
            if not embeddings:
                return []
            hits = chroma_manager.query(embeddings[0], top_k=limit, where={"kind": "doc_chunk"})
            results = []
            for hit in hits:
                item = self._format_vector_hit(hit)
                if item:
                    results.append(item)
            if results:
                return results

            legacy_hits = chroma_manager.query(embeddings[0], top_k=limit)
            return [item for item in (self._format_vector_hit(hit) for hit in legacy_hits) if item]
        except Exception:
            return []

    def _format_vector_hit(self, hit: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = str(hit.get("doc_id", ""))
        metadata = hit.get("metadata") or {}
        score = max(0.0, 1.0 - (hit.get("score", 0.0) / 2.0))

        if doc_id.startswith("chunk:") or metadata.get("kind") == "doc_chunk":
            chunk_id = metadata.get("chunk_id") or doc_id.replace("chunk:", "")
            try:
                chunk = self.db.query(DocumentChunk).filter(DocumentChunk.id == int(chunk_id)).first()
            except Exception:
                chunk = None
            if chunk:
                doc = self.db.query(Document).filter(Document.id == chunk.document_id).first()
                base = {
                    "id": chunk.id,
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": doc.title if doc else metadata.get("title", ""),
                    "content": chunk.content,
                    "score": score,
                    "match_type": "vector",
                    "result_type": "chunk",
                    "source": doc.source if doc else metadata.get("source", ""),
                }
                base.update(self._extract_chunk_metadata(chunk.content))
                base.update({k: v for k, v in metadata.items() if k not in base and isinstance(v, (str, int, float, bool))})
                return base
            item = {
                "id": int(chunk_id) if str(chunk_id).isdigit() else chunk_id,
                "chunk_id": chunk_id,
                "document_id": metadata.get("doc_id"),
                "title": metadata.get("title", ""),
                "content": hit.get("text", ""),
                "score": score,
                "match_type": "vector",
                "result_type": "chunk",
                "source": metadata.get("source", ""),
            }
            item.update(self._extract_chunk_metadata(item["content"]))
            item.update({k: v for k, v in metadata.items() if k not in item and isinstance(v, (str, int, float, bool))})
            return item

        if doc_id.isdigit():
            doc = self.db.query(Document).filter(Document.id == int(doc_id)).first()
            if doc:
                return {
                    "id": doc.id,
                    "document_id": doc.id,
                    "title": doc.title,
                    "content": doc.content[:1200],
                    "score": score,
                    "match_type": "vector",
                    "result_type": "document",
                    "source": doc.source,
                }
        return {}

    def _entity_search(self, terms: List[str], limit: int = 20) -> List[Dict[str, Any]]:
        keywords = []
        for term in terms:
            keywords.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[一-龥]{2,6}", term or ""))
        seen = set()
        keywords = [kw for kw in keywords if not (kw in seen or seen.add(kw))]
        if not keywords:
            return []

        filters = [Node.name.ilike(f"%{kw}%") for kw in keywords[:8]]
        nodes = self.db.query(Node).filter(or_(*filters)).limit(limit).all()
        return [
            {
                "id": node.id,
                "node_id": node.id,
                "name": node.name,
                "type": node.type,
                "description": node.description,
                "score": 0.8,
                "match_type": "keyword",
                "result_type": "node",
            }
            for node in nodes
        ]

    def _merge_and_rank(self, results: Dict[str, Any], plan: RetrievalPlan, top_k: int, query: str = "") -> List[Dict[str, Any]]:
        weights = self._weights_for_plan(plan, query)
        score_map: Dict[str, Dict[str, Any]] = {}

        for route, hits in [
            ("bm25", results.get("bm25_hits", [])),
            ("vector", results.get("semantic_hits", [])),
            ("entity", results.get("entity_hits", [])),
            ("graph", results.get("graph_hits", [])),
        ]:
            weight = weights.get(route, 0.1)
            for rank, hit in enumerate(hits, start=1):
                key = self._hit_key(hit)
                if key not in score_map:
                    score_map[key] = hit.copy()
                    score_map[key]["total_score"] = 0.0
                    score_map[key]["routes"] = []
                score_map[key]["total_score"] += weight / (60 + rank)
                score_map[key]["routes"].append(route)
                score_map[key]["total_score"] += self._hit_boost(hit, route, query, plan)

        merged = sorted(score_map.values(), key=lambda item: item["total_score"], reverse=True)
        return merged[:top_k]

    def _weights_for_plan(self, plan: RetrievalPlan, query: str = "") -> Dict[str, float]:
        q = query or plan.optimized_query or ""
        has_exact_terms = bool(re.search(r"[A-Za-z_][A-Za-z0-9_]{3,}|[A-Z]{2,}|[一-龥]{2,6}", q))
        relation_query = plan.intent in {"relation", "path", "subgraph"} or plan.graph_method in {"path", "subgraph"}
        semantic_query = plan.intent in {"explain", "semantic", "global_summary", "optimize"} or any(
            token in q for token in ["为什么", "如何", "怎么", "原理", "机制", "优势", "区别", "作用", "适合"]
        )

        weights = {"bm25": 1.0, "vector": 1.0, "entity": 0.7, "graph": 0.7}
        if relation_query:
            weights.update({"bm25": 0.9, "vector": 0.9, "entity": 0.9, "graph": 1.8})
        elif semantic_query:
            weights.update({"bm25": 0.85, "vector": 1.55, "entity": 0.45, "graph": 0.45})
        elif plan.intent in {"fact", "exact"} or has_exact_terms:
            weights.update({"bm25": 1.55, "vector": 0.95, "entity": 0.9, "graph": 0.55})

        if has_exact_terms:
            weights["bm25"] += 0.25
        if plan.graph_method in {"path", "subgraph"}:
            weights["graph"] += 0.35
        if plan.intent == "global_summary":
            weights["graph"] = 0.2
        return weights

    def _hit_boost(self, hit: Dict[str, Any], route: str, query: str, plan: RetrievalPlan) -> float:
        title = hit.get("title") or hit.get("name") or ""
        source = hit.get("source") or ""
        text = f"{title}\n{hit.get('content') or hit.get('description') or ''}"
        keywords = self._query_terms(query)
        boost = 0.0

        title_hits = sum(1 for kw in keywords if kw and kw.lower() in title.lower())
        text_hits = sum(1 for kw in keywords if kw and kw.lower() in text.lower())
        if title_hits:
            boost += min(0.012, title_hits * 0.004)
        if route == "bm25" and text_hits:
            boost += min(0.01, text_hits * 0.002)

        if source in {"focused_ai_topic", "ai_doc_extraction"}:
            boost += 0.006
        if route == "graph" and plan.graph_method in {"path", "subgraph"}:
            boost += 0.004
        if route in {"entity", "graph"} and plan.intent in {"explain", "semantic", "global_summary"}:
            boost -= 0.004

        preferred = getattr(plan, "preferred_chunk_types", []) or []
        chunk_type = str(hit.get("chunk_type") or hit.get("section_type") or "")
        if preferred and chunk_type in preferred:
            boost += 0.03 - min(preferred.index(chunk_type), 5) * 0.003
        elif preferred and hit.get("result_type") == "chunk":
            boost -= 0.004
        return boost

    def _query_terms(self, query: str) -> List[str]:
        terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[A-Z]{2,}|[一-龥]{2,6}", query or "")
        seen = set()
        return [term for term in terms if not (term in seen or seen.add(term))][:10]

    def _build_context_text(self, original_query: str, optimized_query: str, plan: RetrievalPlan, results: Dict[str, Any]) -> str:
        parts = [
            f"【用户问题】{original_query}",
            f"【检索理解】{optimized_query}",
            f"【问题意图】{plan.intent}",
        ]

        doc_hits = self._dedupe_hits(results.get("bm25_hits", []) + results.get("semantic_hits", []), "chunk")[:6]
        if doc_hits:
            parts.append("【文档证据】")
            for hit in doc_hits:
                title = hit.get("title", "未命名文档")
                content = (hit.get("content") or "")[:400]
                chunk_type = hit.get("chunk_type") or "chunk"
                section = hit.get("section_path") or ""
                parts.append(f"- {title} [{chunk_type} {section}]: {content}")

        entity_hits = results.get("entity_hits", [])[:5]
        if entity_hits:
            parts.append("【实体证据】")
            for hit in entity_hits:
                parts.append(f"- 【{hit.get('type', 'entity')}】{hit.get('name')}: {hit.get('description') or ''}")

        graph_hits = results.get("graph_hits", [])[:6]
        if graph_hits:
            parts.append("【图谱证据】")
            for hit in graph_hits:
                parts.append(f"- {hit.get('description') or hit.get('name')}")

        return "\n".join(parts)

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

    def _dedupe_hits(self, hits: List[Dict[str, Any]], key_prefix: str) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for hit in hits:
            key = self._hit_key(hit)
            if key_prefix and not key.startswith(key_prefix):
                key = f"{key_prefix}:{key}"
            if key not in seen:
                seen.add(key)
                result.append(hit)
        return result

    def _hit_key(self, hit: Dict[str, Any]) -> str:
        result_type = hit.get("result_type")
        if result_type == "chunk":
            return f"chunk:{hit.get('chunk_id') or hit.get('id')}"
        if result_type == "node":
            return f"node:{hit.get('node_id') or hit.get('id')}"
        if result_type in {"ego", "subgraph", "relation"}:
            return f"edge:{hit.get('edge_id') or hit.get('id')}"
        if result_type == "path":
            return str(hit.get("id"))
        return f"{result_type}:{hit.get('id')}"
