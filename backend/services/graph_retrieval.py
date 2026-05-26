"""
GraphRetrievalService: 统一图检索服务。
在线图检索只保留 ego/path/subgraph 三种方法。
"""

from collections import deque
import re
from typing import Any, Dict, List
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.db import Edge, Node


class GraphRetrievalService:
    """图检索服务"""

    PAPER_RELATION_PRIORITY = {
        "PAPER_HAS_SECTION": 0,
        "CHILD_SECTION": 1,
        "SECTION_HAS_CHUNK": 2,
        "METHOD_EVALUATED_ON_DATASET": 3,
        "METHOD_REPORTED_METRIC": 3,
        "SECTION_HAS_TABLE": 4,
        "SECTION_HAS_CODE": 4,
        "SECTION_HAS_EQUATION": 4,
        "PAPER_HAS_METHOD": 5,
        "PAPER_CITES_PAPER": 6,
        "NEXT_CHUNK": 8,
        "PREV_CHUNK": 8,
    }
    PAPER_NODE_TYPES = {"paper", "section", "chunk", "table", "code", "equation", "reference", "method", "dataset", "metric"}
    PAPER_QUERY_TOKENS = ["论文", "章节", "结构", "方法", "实验", "数据集", "指标", "引用", "参考文献", "paper", "section", "method", "dataset", "metric", "reference"]

    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        method: str,
        entities: List[str],
        seed_node_ids: List[int],
        query: str,
        limit: int = 10,
        depth: int = 1,
    ) -> List[Dict[str, Any]]:
        if method == "none":
            return []

        seeds = self._resolve_seed_ids(entities, seed_node_ids, query, limit=8)
        if not seeds:
            return []

        if self._is_paper_query(query, seeds):
            return self._search_paper_graph(method, seeds, query, limit=limit, depth=depth)

        if method == "path":
            return self._search_path(seeds, max_depth=min(max(depth, 2), 3), limit=limit)
        if method == "subgraph":
            return self._search_subgraph(seeds, depth=min(max(depth, 1), 2), limit=limit)
        return self._search_ego(seeds, limit=limit)

    def _resolve_seed_ids(self, entities: List[str], seed_node_ids: List[int], query: str, limit: int) -> List[int]:
        seed_ids = []
        seen = set()

        for node_id in seed_node_ids:
            if node_id and node_id not in seen:
                seen.add(node_id)
                seed_ids.append(node_id)

        names = [entity.strip() for entity in entities if entity.strip()]
        if not names:
            names = self._query_terms(query)

        for name in names[:8]:
            nodes = (
                self.db.query(Node)
                .filter(Node.name.ilike(f"%{name}%"))
                .order_by(Node.confidence.desc())
                .limit(5)
                .all()
            )
            for node in nodes:
                if node.id not in seen:
                    seen.add(node.id)
                    seed_ids.append(node.id)
                if len(seed_ids) >= limit:
                    return seed_ids
        return seed_ids[:limit]

    def _search_ego(self, seed_ids: List[int], limit: int) -> List[Dict[str, Any]]:
        edges = (
            self.db.query(Edge)
            .filter(or_(Edge.source_id.in_(seed_ids), Edge.target_id.in_(seed_ids)))
            .order_by(Edge.confidence.desc())
            .limit(limit * 2)
            .all()
        )
        return self._format_edges(edges, "ego", limit)

    def _search_path(self, seed_ids: List[int], max_depth: int, limit: int) -> List[Dict[str, Any]]:
        if len(seed_ids) < 2:
            return self._search_ego(seed_ids, limit)

        targets = set(seed_ids[1:])
        queue = deque([(seed_ids[0], [], {seed_ids[0]})])
        paths = []

        while queue and len(paths) < limit:
            node_id, path_edges, visited = queue.popleft()
            if len(path_edges) >= max_depth:
                continue

            edges = (
                self.db.query(Edge)
                .filter(or_(Edge.source_id == node_id, Edge.target_id == node_id))
                .order_by(Edge.confidence.desc())
                .limit(20)
                .all()
            )
            for edge in edges:
                next_id = edge.target_id if edge.source_id == node_id else edge.source_id
                if next_id in visited:
                    continue
                new_path = path_edges + [edge]
                if next_id in targets:
                    paths.append(self._format_path(new_path))
                    if len(paths) >= limit:
                        break
                else:
                    queue.append((next_id, new_path, visited | {next_id}))

        if paths:
            return paths
        return self._search_ego(seed_ids, limit)

    def _search_subgraph(self, seed_ids: List[int], depth: int, limit: int) -> List[Dict[str, Any]]:
        current_ids = set(seed_ids)
        visited_ids = set(seed_ids)
        collected_edges = []

        for _ in range(depth):
            if not current_ids:
                break
            edges = (
                self.db.query(Edge)
                .filter(or_(Edge.source_id.in_(current_ids), Edge.target_id.in_(current_ids)))
                .order_by(Edge.confidence.desc())
                .limit(limit * 3)
                .all()
            )
            next_ids = set()
            for edge in edges:
                collected_edges.append(edge)
                for node_id in (edge.source_id, edge.target_id):
                    if node_id not in visited_ids:
                        visited_ids.add(node_id)
                        next_ids.add(node_id)
                if len(collected_edges) >= limit:
                    break
            current_ids = next_ids
            if len(collected_edges) >= limit:
                break

        return self._format_edges(collected_edges, "subgraph", limit)

    def _search_paper_graph(self, method: str, seed_ids: List[int], query: str, limit: int, depth: int) -> List[Dict[str, Any]]:
        seed_ids = self._expand_to_paper_seeds(seed_ids)
        relation_filter = self._paper_relation_filter(query)
        if method == "path":
            path_results = self._search_paper_paths(seed_ids, query, limit)
            if path_results:
                return path_results
        if method == "ego":
            edges = self._paper_edges(seed_ids, relation_filter, limit * 4)
            return self._format_edges(self._rank_paper_edges(edges, query), "paper_ego", limit)

        collected = []
        current_ids = set(seed_ids)
        visited_ids = set(seed_ids)
        for _ in range(min(max(depth, 1), 3)):
            edges = self._paper_edges(list(current_ids), relation_filter, limit * 5)
            next_ids = set()
            for edge in self._rank_paper_edges(edges, query):
                if edge.id not in {item.id for item in collected}:
                    collected.append(edge)
                for node_id in (edge.source_id, edge.target_id):
                    if node_id not in visited_ids:
                        visited_ids.add(node_id)
                        next_ids.add(node_id)
                if len(collected) >= limit:
                    break
            current_ids = next_ids
            if not current_ids or len(collected) >= limit:
                break
        return self._format_edges(collected, "paper_subgraph", limit)

    def _search_paper_paths(self, seed_ids: List[int], query: str, limit: int) -> List[Dict[str, Any]]:
        target_types = self._target_node_types(query)
        if not target_types and len(seed_ids) >= 2:
            return self._search_path(seed_ids, max_depth=3, limit=limit)

        queue = deque((seed_id, [], {seed_id}) for seed_id in seed_ids)
        paths = []
        while queue and len(paths) < limit:
            node_id, path_edges, visited = queue.popleft()
            if len(path_edges) >= 3:
                continue
            edges = self._paper_edges([node_id], [], limit=30)
            for edge in self._rank_paper_edges(edges, query):
                next_id = edge.target_id if edge.source_id == node_id else edge.source_id
                if next_id in visited:
                    continue
                new_path = path_edges + [edge]
                next_node = self.db.query(Node).filter(Node.id == next_id).first()
                if next_node and next_node.type in target_types:
                    paths.append(self._format_path(new_path, result_type="paper_path"))
                    if len(paths) >= limit:
                        break
                queue.append((next_id, new_path, visited | {next_id}))
        return paths

    def _paper_edges(self, seed_ids: List[int], relation_filter: List[str], limit: int) -> List[Edge]:
        query = self.db.query(Edge).filter(or_(Edge.source_id.in_(seed_ids), Edge.target_id.in_(seed_ids)))
        if relation_filter:
            query = query.filter(Edge.relation.in_(relation_filter))
        return query.order_by(Edge.confidence.desc()).limit(limit).all()

    def _rank_paper_edges(self, edges: List[Edge], query: str) -> List[Edge]:
        def score(edge: Edge) -> tuple:
            source = self.db.query(Node).filter(Node.id == edge.source_id).first()
            target = self.db.query(Node).filter(Node.id == edge.target_id).first()
            type_bonus = 0 if self._edge_has_paper_node(source, target) else 5
            relation_rank = self.PAPER_RELATION_PRIORITY.get(edge.relation, 10)
            query_bonus = -2 if self._edge_matches_query(edge, source, target, query) else 0
            return (type_bonus, relation_rank + query_bonus, -(edge.confidence or 0.0))
        return sorted(edges, key=score)

    def _format_edges(self, edges: List[Edge], method: str, limit: int) -> List[Dict[str, Any]]:
        results = []
        for edge in edges[:limit]:
            source = self.db.query(Node).filter(Node.id == edge.source_id).first()
            target = self.db.query(Node).filter(Node.id == edge.target_id).first()
            if not source or not target:
                continue
            results.append({
                "id": edge.id,
                "edge_id": edge.id,
                "source_id": source.id,
                "target_id": target.id,
                "source": source.name,
                "target": target.name,
                "source_type": source.type,
                "target_type": target.type,
                "relation": edge.relation,
                "score": edge.confidence or 0.6,
                "match_type": "graph",
                "result_type": method,
                "name": f"{source.name} -{edge.relation}-> {target.name}",
                "type": "relation",
                "description": f"{source.name} {edge.relation} {target.name}",
                "metadata": {
                    "source_properties": source.properties or {},
                    "target_properties": target.properties or {},
                    "edge_type": edge.type,
                },
            })
        return results

    def _format_path(self, edges: List[Edge], result_type: str = "path") -> Dict[str, Any]:
        parts = []
        score = 0.0
        node_types = []
        for edge in edges:
            source = self.db.query(Node).filter(Node.id == edge.source_id).first()
            target = self.db.query(Node).filter(Node.id == edge.target_id).first()
            if source and target:
                parts.append(f"{source.name} -{edge.relation}-> {target.name}")
                node_types.extend([source.type, target.type])
                score += edge.confidence or 0.6
        path_text = " | ".join(parts)
        return {
            "id": "path:" + ":".join(str(edge.id) for edge in edges),
            "path_edges": [edge.id for edge in edges],
            "name": path_text,
            "description": path_text,
            "score": score / max(1, len(edges)),
            "match_type": "graph",
            "result_type": result_type,
            "type": "path",
            "node_types": sorted(set(node_types)),
        }

    def _is_paper_query(self, query: str, seed_ids: List[int]) -> bool:
        query_lower = (query or "").lower()
        if any(token in query_lower for token in self.PAPER_QUERY_TOKENS):
            return True
        nodes = self.db.query(Node).filter(Node.id.in_(seed_ids)).all()
        return any(node.type in self.PAPER_NODE_TYPES for node in nodes)

    def _expand_to_paper_seeds(self, seed_ids: List[int]) -> List[int]:
        seeds = list(dict.fromkeys(seed_ids))
        nodes = self.db.query(Node).filter(Node.id.in_(seed_ids)).all()
        doc_ids = []
        for node in nodes:
            props = node.properties or {}
            doc_id = props.get("document_id")
            if doc_id and doc_id not in doc_ids:
                doc_ids.append(doc_id)
        if doc_ids:
            papers = (
                self.db.query(Node)
                .filter(Node.type == "paper")
                .all()
            )
            for paper in papers:
                if (paper.properties or {}).get("document_id") in doc_ids and paper.id not in seeds:
                    seeds.insert(0, paper.id)
        return seeds[:10]

    def _paper_relation_filter(self, query: str) -> List[str]:
        q = query or ""
        relations = []
        if any(token in q for token in ["章节", "结构", "大纲", "section", "outline"]):
            relations.extend(["PAPER_HAS_SECTION", "CHILD_SECTION", "SECTION_HAS_CHUNK"])
        if any(token in q for token in ["实验", "数据集", "指标", "评估", "dataset", "metric", "benchmark"]):
            relations.extend(["METHOD_EVALUATED_ON_DATASET", "METHOD_REPORTED_METRIC", "SECTION_HAS_TABLE", "SECTION_HAS_CHUNK"])
        if any(token in q for token in ["方法", "模型", "算法", "method", "model"]):
            relations.extend(["PAPER_HAS_METHOD", "SECTION_HAS_CODE", "SECTION_HAS_CHUNK"])
        if any(token in q for token in ["引用", "参考文献", "相关工作", "citation", "reference"]):
            relations.extend(["PAPER_CITES_PAPER", "SECTION_HAS_REFERENCE", "SECTION_HAS_CHUNK"])
        return list(dict.fromkeys(relations))

    def _target_node_types(self, query: str) -> List[str]:
        q = query or ""
        types = []
        if any(token in q for token in ["数据集", "dataset", "benchmark"]):
            types.append("dataset")
        if any(token in q for token in ["指标", "metric", "bleu", "f1", "accuracy"]):
            types.append("metric")
        if any(token in q for token in ["表格", "table", "结果"]):
            types.append("table")
        if any(token in q for token in ["代码", "code"]):
            types.append("code")
        if any(token in q for token in ["引用", "参考文献", "reference"]):
            types.append("reference")
        return types

    def _edge_has_paper_node(self, source: Node, target: Node) -> bool:
        return bool(source and target and (source.type in self.PAPER_NODE_TYPES or target.type in self.PAPER_NODE_TYPES))

    def _edge_matches_query(self, edge: Edge, source: Node, target: Node, query: str) -> bool:
        text = f"{edge.relation} {source.name if source else ''} {target.name if target else ''}".lower()
        terms = [term.lower() for term in self._query_terms(query) if len(term) >= 2]
        return any(term in text for term in terms[:8])

    def _query_terms(self, query: str) -> List[str]:
        return re.findall(r"[一-龥a-zA-Z0-9_.-]{2,}", query or "")
