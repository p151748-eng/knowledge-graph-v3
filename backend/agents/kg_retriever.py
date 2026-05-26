"""
KGRetriever Agent: 从知识图谱检索相关实体、关系和文档。
绑定 HybridSearchTool，执行混合检索。
"""

from typing import Any, Dict
from sqlalchemy.orm import Session

from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from models.schemas import RetrievalData
from tools.hybrid_search import HybridSearchTool


class KGRetrieverAgent(BaseAgent):
    """知识图谱检索 Agent"""

    def __init__(self, db: Session, embedding_service: Any = None):
        super().__init__(
            name="KGRetriever",
            role="retriever",
            description="从知识图谱检索相关实体、关系和文档"
        )
        self.db = db
        self.search_tool = HybridSearchTool(db, embedding_service)

    def execute(self, context: AgentContext) -> AgentResult:
        """执行检索"""
        query = context.pipeline_data.query
        if not query:
            return AgentResult(
                success=False,
                output=None,
                message="查询为空"
            )

        # 执行混合检索
        memory_context = context.extra.get("memory_context", "") if context.extra else ""
        retrieval_query = f"{query}\n\n{memory_context}" if memory_context else query
        search_result = self.search_tool.execute(retrieval_query, top_k=10)

        # 构建 context_text
        merged = search_result.get("merged", [])
        entities = [item for item in merged if item.get("result_type") in {"node", "ego", "subgraph", "path", "relation"}]
        doc_chunks = search_result.get("bm25_hits", []) + search_result.get("semantic_hits", [])
        context_text = search_result.get("context_text", "")

        # 构建 RetrievalData
        retrieval_data = RetrievalData(
            entities=entities,
            relations=search_result.get("graph_hits", []),
            context_text=context_text,
            doc_chunks=doc_chunks,
        )
        context.pipeline_data.retrieval_data = retrieval_data

        return AgentResult(
            success=True,
            output={"entities": entities, "context_text": context_text, "doc_chunks": doc_chunks},
            message=f"检索到 {len(merged)} 个相关结果",
            confidence=0.8,
        )
