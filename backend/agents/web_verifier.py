"""
WebSearchVerifierAgent: 在 CRAG 兜底阶段联网查找并筛选可靠证据。
"""

from typing import Any, Dict, List
from urllib.parse import urlparse

from config import config
from core.agent import AgentResult, BaseAgent
from core.context import AgentContext
from tools.web_search import WebSearchTool


WEB_EVIDENCE_GRADER_PROMPT = """你是 Web 证据评估器，请判断网页摘要是否能补足本地证据缺口，不要回答用户问题。

【用户问题】
{query}

【缺失方面】
{missing_aspects}

【网页候选证据】
{evidence}

请输出 JSON：
{{
  "accepted": [
    {{"index": 0, "score": 0.0到1.0, "reason": "理由"}}
  ]
}}

只接受相关、非模拟、URL 有效、能支撑缺失方面的结果。不要输出 JSON 外的任何文字。
"""


class WebSearchVerifierAgent(BaseAgent):
    """联网证据查找与验证 Agent"""

    def __init__(self, db, llm=None, min_score: float | None = None):
        super().__init__(
            name="WebSearchVerifier",
            role="web_verifier",
            description="联网查找并验证临时外部证据",
        )
        from llm.manager import llm_manager
        self.db = db
        self.llm = llm if llm is not None else llm_manager
        self.min_score = min_score if min_score is not None else config.CRAG_WEB_MIN_SCORE

    def execute(self, context: AgentContext) -> AgentResult:
        query = context.extra.get("query") or context.pipeline_data.query
        grade = context.extra.get("grade") or context.pipeline_data.evidence_grade
        evidence = self.search_and_grade(query, grade)
        context.pipeline_data.web_evidence = evidence
        return AgentResult(
            success=True,
            output=evidence,
            message=f"接受 {len(evidence)} 条联网证据",
            confidence=0.8 if evidence else 0.2,
        )

    def search_and_grade(self, query: str, grade=None, max_results: int | None = None) -> List[Dict[str, Any]]:
        max_results = max_results or config.CRAG_WEB_MAX_RESULTS
        search_query = self._web_query(query, grade)
        raw = WebSearchTool(self.db).execute(search_query, max_results=max_results, save=False)
        candidates = [self._normalize(item, idx) for idx, item in enumerate(raw.get("results", []))]
        candidates = [item for item in candidates if self._is_candidate_usable(item)]
        if not candidates:
            return []
        accepted = self._grade_with_llm(query, candidates, grade)
        return accepted or self._heuristic_accept(candidates)

    def _web_query(self, query: str, grade=None) -> str:
        missing = "; ".join(grade.missing_aspects if grade else [])
        if missing:
            return f"{query} {missing}"
        return query

    def _normalize(self, item: Dict[str, Any], index: int) -> Dict[str, Any]:
        return {
            "id": index,
            "index": index,
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "source": "web_search",
            "result_type": "web_evidence",
            "type": "web",
            "provider": item.get("provider", ""),
            "rank": item.get("rank", index + 1),
            "quality_score": item.get("quality_score", 0.0),
            "query": item.get("query", ""),
        }

    def _is_candidate_usable(self, item: Dict[str, Any]) -> bool:
        title = item.get("title", "")
        url = item.get("url", "")
        if not url or url == "https://example.com":
            return False
        if title.startswith("[模拟]") or title == "搜索失败":
            return False
        if item.get("snippet"):
            return True
        return item.get("quality_score", 0) >= 0.55 or self._is_authoritative_url(url)

    def _is_authoritative_url(self, url: str) -> bool:
        domain = urlparse(url if "://" in url else "https://" + url).netloc.lower()
        return any(domain.endswith(auth) for auth in ["arxiv.org", "aclanthology.org", "openreview.net", "microsoft.com", "github.com", "semanticscholar.org"])

    def _grade_with_llm(self, query: str, candidates: List[Dict[str, Any]], grade=None) -> List[Dict[str, Any]]:
        try:
            prompt = WEB_EVIDENCE_GRADER_PROMPT.format(
                query=query,
                missing_aspects="; ".join(grade.missing_aspects if grade else []),
                evidence=[{k: v for k, v in item.items() if k in {"index", "title", "url", "snippet"}} for item in candidates],
            )
            data = self.llm.complete_json(prompt, {})
            accepted = []
            for item in data.get("accepted", []):
                index = item.get("index")
                score = float(item.get("score", 0))
                if score < self.min_score:
                    continue
                match = next((candidate for candidate in candidates if candidate["index"] == index), None)
                if match:
                    enriched = match.copy()
                    enriched["score"] = score
                    enriched["reason"] = item.get("reason", "")
                    accepted.append(enriched)
            return accepted
        except Exception:
            return []

    def _heuristic_accept(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        accepted = []
        ranked = sorted(candidates, key=lambda item: (-float(item.get("quality_score", 0)), item.get("rank", 99)))
        for item in ranked[:3]:
            enriched = item.copy()
            enriched["score"] = max(self.min_score, float(item.get("quality_score", 0)))
            enriched["reason"] = "通过 URL、摘要与来源质量检查"
            accepted.append(enriched)
        return accepted
