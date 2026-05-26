"""
EvidenceGraderAgent: 评估检索证据是否足以支撑回答。
"""

import re
from typing import Any, Dict, List

from core.agent import AgentResult, BaseAgent
from core.context import AgentContext
from models.schemas import EvidenceGradeData


EVIDENCE_GRADER_PROMPT = """你是 CRAG 证据评估器，只判断检索证据是否足以支撑回答，不要回答用户问题。

【用户问题】
{query}

【检索计划】
{plan}

【检索证据】
{context_text}

【证据摘要】
BM25 命中数: {bm25_count}
向量命中数: {vector_count}
图谱命中数: {graph_count}

请输出 JSON：
{{
  "relevance_score": 0.0到1.0,
  "support_score": 0.0到1.0,
  "coverage_score": 0.0到1.0,
  "freshness_required": true或false,
  "conflict_detected": true或false,
  "sufficient": true或false,
  "missing_aspects": ["缺失点"],
  "next_action": "answer | rewrite_local | adjust_strategy | web_verify | refuse",
  "reason": "简短理由"
}}

判断规则：
- 只有证据和问题高度相关、能支撑主要结论、覆盖主要方面时 sufficient 才为 true。
- 如果问题涉及时效性、版本、发布记录、论文或基准测试，freshness_required=true。
- 如果本地证据不足但仍可通过改写本地查询补救，next_action=rewrite_local 或 adjust_strategy。
- 如果需要外部新知识或本地重试仍不足，next_action=web_verify。
- 如果明显无法回答且不适合联网，next_action=refuse。
- 不要输出 JSON 外的任何文字。
"""


class EvidenceGraderAgent(BaseAgent):
    """检索证据质量评估 Agent"""

    ACTIONS = {"answer", "rewrite_local", "adjust_strategy", "web_verify", "refuse"}
    FRESHNESS_TERMS = ["最新", "当前", "近期", "现在", "2026", "version", "release", "changelog", "paper", "论文", "benchmark"]

    def __init__(self, llm=None):
        super().__init__(
            name="EvidenceGrader",
            role="evidence_grader",
            description="评估本地或联网证据是否足以支撑用户问题",
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    def execute(self, context: AgentContext) -> AgentResult:
        retrieval = context.extra.get("retrieval", {})
        query = context.extra.get("query") or context.pipeline_data.query
        grade = self.grade(query, retrieval, round_index=context.extra.get("round", 1))
        context.pipeline_data.evidence_grade = grade
        return AgentResult(
            success=True,
            output=grade,
            message=grade.reason or "证据评估完成",
            confidence=grade.coverage_score,
        )

    def grade(self, query: str, retrieval: Dict[str, Any], round_index: int = 1) -> EvidenceGradeData:
        fallback = self._heuristic_grade(query, retrieval, round_index)
        try:
            prompt = EVIDENCE_GRADER_PROMPT.format(
                query=query,
                plan=retrieval.get("plan", {}),
                context_text=(retrieval.get("context_text") or "")[:5000],
                bm25_count=len(retrieval.get("bm25_hits", [])),
                vector_count=len(retrieval.get("semantic_hits", [])),
                graph_count=len(retrieval.get("graph_hits", [])),
            )
            data = self.llm.complete_json(prompt, {})
            return self._normalize(data, fallback=fallback)
        except Exception:
            return fallback

    def _heuristic_grade(self, query: str, retrieval: Dict[str, Any], round_index: int = 1) -> EvidenceGradeData:
        context_text = retrieval.get("context_text") or ""
        merged = retrieval.get("merged", [])
        freshness_required = any(term.lower() in query.lower() for term in self.FRESHNESS_TERMS)
        query_terms = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[一-龥]{2,6}", query or ""))
        text = context_text.lower()
        matched = sum(1 for term in query_terms if term.lower() in text)
        relevance = min(1.0, 0.25 + matched / max(len(query_terms), 1) * 0.6 + min(len(merged), 5) * 0.03)
        support = min(1.0, 0.2 + min(len(context_text), 1600) / 1600 * 0.45 + min(len(merged), 5) * 0.05)
        coverage = min(1.0, (relevance + support) / 2)
        sufficient = relevance >= 0.7 and support >= 0.7 and coverage >= 0.65 and not freshness_required
        if sufficient:
            action = "answer"
        elif freshness_required or round_index >= 2:
            action = "web_verify"
        else:
            action = "rewrite_local" if merged else "adjust_strategy"
        return EvidenceGradeData(
            relevance_score=round(relevance, 2),
            support_score=round(support, 2),
            coverage_score=round(coverage, 2),
            freshness_required=freshness_required,
            conflict_detected=False,
            sufficient=sufficient,
            missing_aspects=[] if sufficient else ["现有证据不足以完整支撑回答"],
            next_action=action,
            reason="基于检索命中和问题关键词的启发式评估",
        )

    def _normalize(self, data: Dict[str, Any], fallback: EvidenceGradeData) -> EvidenceGradeData:
        action = str(data.get("next_action") or fallback.next_action)
        if action not in self.ACTIONS:
            action = fallback.next_action
        grade = EvidenceGradeData(
            relevance_score=self._score(data.get("relevance_score"), fallback.relevance_score),
            support_score=self._score(data.get("support_score"), fallback.support_score),
            coverage_score=self._score(data.get("coverage_score"), fallback.coverage_score),
            freshness_required=bool(data.get("freshness_required", fallback.freshness_required)),
            conflict_detected=bool(data.get("conflict_detected", fallback.conflict_detected)),
            sufficient=bool(data.get("sufficient", fallback.sufficient)),
            missing_aspects=self._list(data.get("missing_aspects")) or fallback.missing_aspects,
            next_action=action,
            reason=str(data.get("reason") or fallback.reason),
        )
        if grade.sufficient:
            grade.next_action = "answer"
        return grade

    def _score(self, value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return default

    def _list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()][:5]
        return []
