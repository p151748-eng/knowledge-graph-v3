"""
RetrievalRepairAgent: 根据证据缺口改写查询并生成受控检索策略覆盖。
"""

from typing import Any, Dict, List

from core.agent import AgentResult, BaseAgent
from core.context import AgentContext
from models.schemas import EvidenceGradeData


RETRIEVAL_REPAIR_PROMPT = """你是 CRAG 检索修正器，只能改写查询和建议受控检索策略，不要回答用户问题。

【用户问题】
{query}

【当前检索计划】
{plan}

【证据评估】
{grade}

【缺失方面】
{missing_aspects}

请输出 JSON：
{{
  "rewritten_query": "更明确的检索问题",
  "expanded_queries": ["补充查询1", "补充查询2"],
  "strategy": {{
    "bm25": true,
    "vector": true,
    "graph": true,
    "graph_method": "none | ego | path | subgraph",
    "bm25_top_k": 12,
    "vector_top_k": 12,
    "graph_top_k": 10
  }},
  "reason": "简短理由"
}}

约束：
- graph_method 只能是 none、ego、path、subgraph。
- top_k 最大 20。
- expanded_queries 最多 2 条。
- 不要输出 JSON 外的任何文字。
"""


class RetrievalRepairAgent(BaseAgent):
    """检索修正 Agent"""

    GRAPH_METHODS = {"none", "ego", "path", "subgraph"}
    STRATEGY_KEYS = {"bm25", "vector", "graph", "graph_method", "bm25_top_k", "vector_top_k", "graph_top_k", "graph_depth", "expanded_queries"}

    def __init__(self, llm=None):
        super().__init__(
            name="RetrievalRepair",
            role="retrieval_repair",
            description="根据证据缺口改写检索问题和调整检索策略",
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    def execute(self, context: AgentContext) -> AgentResult:
        query = context.extra.get("query") or context.pipeline_data.query
        retrieval = context.extra.get("retrieval", {})
        grade = context.extra.get("grade") or context.pipeline_data.evidence_grade
        output = self.repair(query, retrieval, grade)
        return AgentResult(
            success=True,
            output=output,
            message=output.get("reason", "检索修正完成"),
            confidence=0.7,
        )

    def repair(self, query: str, retrieval: Dict[str, Any], grade: EvidenceGradeData | None) -> Dict[str, Any]:
        fallback = self._fallback(query, retrieval, grade)
        try:
            prompt = RETRIEVAL_REPAIR_PROMPT.format(
                query=query,
                plan=retrieval.get("plan", {}),
                grade=grade.__dict__ if grade else {},
                missing_aspects="; ".join(grade.missing_aspects if grade else []),
            )
            data = self.llm.complete_json(prompt, {})
            return self._normalize(data, fallback)
        except Exception:
            return fallback

    def _fallback(self, query: str, retrieval: Dict[str, Any], grade: EvidenceGradeData | None) -> Dict[str, Any]:
        plan = retrieval.get("plan", {}) or {}
        graph_method = plan.get("graph_method", "none")
        if graph_method == "none" and any(token in query for token in ["关系", "影响", "链路", "上下游", "架构", "模块"]):
            graph_method = "subgraph" if any(token in query for token in ["上下游", "架构", "模块"]) else "path"
        strategy = {
            "bm25": True,
            "vector": True,
            "graph": graph_method != "none",
            "graph_method": graph_method if graph_method in self.GRAPH_METHODS else "none",
            "bm25_top_k": min(20, max(12, int(plan.get("bm25_top_k", 8) or 8))),
            "vector_top_k": min(20, max(12, int(plan.get("vector_top_k", 8) or 8))),
            "graph_top_k": min(20, max(10, int(plan.get("graph_top_k", 8) or 8))),
        }
        missing = " ".join(grade.missing_aspects if grade else [])
        rewritten = f"{query} {missing}".strip()
        return {
            "rewritten_query": rewritten or query,
            "expanded_queries": [query] if rewritten != query else [],
            "strategy": strategy,
            "reason": "根据证据缺口提高本地检索覆盖率",
        }

    def _normalize(self, data: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        strategy = fallback["strategy"].copy()
        incoming = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
        for key, value in incoming.items():
            if key not in self.STRATEGY_KEYS:
                continue
            if key.endswith("top_k") or key == "graph_depth":
                try:
                    strategy[key] = max(1, min(20, int(value)))
                except Exception:
                    pass
            elif key == "graph_method":
                strategy[key] = value if value in self.GRAPH_METHODS else strategy.get("graph_method", "none")
            else:
                strategy[key] = bool(value)
        rewritten_query = str(data.get("rewritten_query") or fallback["rewritten_query"]).strip()
        expanded = data.get("expanded_queries") if isinstance(data.get("expanded_queries"), list) else fallback.get("expanded_queries", [])
        return {
            "rewritten_query": rewritten_query or fallback["rewritten_query"],
            "expanded_queries": [str(item) for item in expanded if str(item).strip()][:2],
            "strategy": strategy,
            "reason": str(data.get("reason") or fallback["reason"]),
        }
