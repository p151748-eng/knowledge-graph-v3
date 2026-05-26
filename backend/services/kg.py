"""
KGService: 知识图谱管理服务。
节点和边的 CRUD，以及图谱可视化数据。
"""

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.db import Node, Edge, Document


class KGService:
    """知识图谱服务"""

    def __init__(self, db: Session):
        self.db = db

    # ── 节点 CRUD ──────────────────────────────────────────────

    def list_nodes(
        self,
        search: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Node], int]:
        """获取节点列表"""
        query = self.db.query(Node)
        if search:
            query = query.filter(Node.name.ilike(f"%{search}%"))
        if node_type:
            query = query.filter(Node.type == node_type)

        total = query.count()
        nodes = query.order_by(Node.updated_at.desc()).offset(offset).limit(limit).all()
        return nodes, total

    def get_node(self, node_id: int) -> Optional[Node]:
        """获取单个节点"""
        return self.db.query(Node).filter(Node.id == node_id).first()

    def create_node(
        self,
        name: str,
        node_type: str = "entity",
        description: Optional[str] = None,
        source_doc_ids: Optional[List[int]] = None,
    ) -> Node:
        """创建节点"""
        node = Node(
            name=name,
            type=node_type,
            description=description,
            source_doc_ids=source_doc_ids,
        )
        self.db.add(node)
        self.db.commit()
        self.db.refresh(node)
        return node

    def update_node(self, node_id: int, name: Optional[str] = None, description: Optional[str] = None) -> Optional[Node]:
        """更新节点"""
        node = self.db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return None
        if name is not None:
            node.name = name
        if description is not None:
            node.description = description
        self.db.commit()
        self.db.refresh(node)
        return node

    def delete_node(self, node_id: int) -> bool:
        """删除节点（关联边级联删除）"""
        node = self.db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return False
        self.db.delete(node)
        self.db.commit()
        return True

    # ── 关系 CRUD ──────────────────────────────────────────────

    def list_edges(
        self,
        source_id: Optional[int] = None,
        target_id: Optional[int] = None,
        relation: Optional[str] = None,
        limit: int = 200,
    ) -> List[Edge]:
        """获取关系列表"""
        query = self.db.query(Edge)
        if source_id:
            query = query.filter(Edge.source_id == source_id)
        if target_id:
            query = query.filter(Edge.target_id == target_id)
        if relation:
            query = query.filter(Edge.relation.ilike(f"%{relation}%"))

        edges = query.limit(limit).all()
        return edges

    def create_edge(
        self,
        source_id: int,
        target_id: int,
        relation: str,
        confidence: float = 0.8,
    ) -> Optional[Edge]:
        """创建关系"""
        if source_id == target_id:
            return None
        existing = (
            self.db.query(Edge)
            .filter(Edge.source_id == source_id, Edge.target_id == target_id, Edge.relation == relation)
            .first()
        )
        if existing:
            return existing

        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            confidence=confidence,
        )
        self.db.add(edge)
        self.db.commit()
        self.db.refresh(edge)
        return edge

    def delete_edge(self, edge_id: int) -> bool:
        """删除关系"""
        edge = self.db.query(Edge).filter(Edge.id == edge_id).first()
        if not edge:
            return False
        self.db.delete(edge)
        self.db.commit()
        return True

    # ── 搜索 ────────────────────────────────────────────────────

    def search(self, q: str, mode: str = "hybrid", top_k: int = 10) -> Dict[str, Any]:
        """KG 混合检索"""
        from tools.hybrid_search import HybridSearchTool
        from llm.manager import llm_manager

        tool = HybridSearchTool(self.db, llm_manager)
        result = tool.execute(q, top_k=top_k)

        entities = [
            {
                "id": e.get("node_id", e.get("id")),
                "name": e.get("name", ""),
                "type": e.get("type", "entity"),
                "description": e.get("description"),
                "score": e.get("total_score", e.get("score", 0)),
                "match_type": e.get("match_type", "hybrid"),
            }
            for e in result.get("merged", [])
            if e.get("result_type") == "node"
        ]

        relations = [
            {
                "source": e.get("source", ""),
                "relation": e.get("relation", ""),
                "target": e.get("target", ""),
            }
            for e in result.get("graph_hits", [])
            if e.get("source") and e.get("target")
        ]

        return {
            "entities": entities,
            "relations": relations,
            "mode": mode,
        }

    # ── 图谱可视化数据 ──────────────────────────────────────────

    def get_full_graph(self, limit: int = 100) -> Tuple[List[Node], List[Edge]]:
        """获取全量图谱数据"""
        nodes = self.db.query(Node).limit(limit).all()
        node_ids = [n.id for n in nodes]
        edges = (
            self.db.query(Edge)
            .filter(Edge.source_id.in_(node_ids), Edge.target_id.in_(node_ids))
            .all()
        )
        return nodes, edges

    def get_subgraph(self, center_id: int, depth: int = 1, limit: int = 100) -> Tuple[List[Node], List[Edge]]:
        """获取子图（以某节点为中心扩散）"""
        center_node = self.db.query(Node).filter(Node.id == center_id).first()
        if not center_node:
            return [], []

        nodes_map = {center_id: center_node}
        edge_list = []

        current_ids = {center_id}
        for _ in range(depth):
            neighbors = (
                self.db.query(Edge)
                .filter(Edge.source_id.in_(current_ids) | Edge.target_id.in_(current_ids))
                .all()
            )
            new_ids = set()
            for e in neighbors:
                edge_list.append(e)
                if e.source_id not in nodes_map:
                    src = self.db.query(Node).filter(Node.id == e.source_id).first()
                    if src:
                        nodes_map[e.source_id] = src
                        new_ids.add(e.source_id)
                if e.target_id not in nodes_map:
                    tgt = self.db.query(Node).filter(Node.id == e.target_id).first()
                    if tgt:
                        nodes_map[e.target_id] = tgt
                        new_ids.add(e.target_id)
            current_ids = new_ids
            if len(nodes_map) >= limit:
                break

        return list(nodes_map.values()), edge_list[:limit]

    def get_graph_data(self, center_id: Optional[int] = None, depth: int = 1, limit: int = 100) -> Dict[str, Any]:
        """获取图谱可视化数据"""
        TYPE_TO_GROUP = {"concept": 1, "entity": 2, "document": 3}
        if center_id:
            nodes, edges = self.get_subgraph(center_id, depth, limit)
        else:
            nodes, edges = self.get_full_graph(limit)

        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "type": n.type,
                    "group": TYPE_TO_GROUP.get(n.type, 0),
                    "description": n.description,
                }
                for n in nodes
            ],
            "links": [
                {"source": e.source_id, "target": e.target_id, "relation": e.relation}
                for e in edges
            ],
        }
