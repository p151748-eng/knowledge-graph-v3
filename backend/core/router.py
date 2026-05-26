"""
Context-aware routing for chat workflows.
"""

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Dict, List, Optional


PATH_ALIASES = {
    "simple": "fast",
    "complex": "pipeline",
    "paper": "paper_assistant",
    "crag": "self_rag",
    "research_workflow": "research",
}
VALID_PATHS = {"fast", "pipeline", "self_rag", "paper_assistant", "research"}


@dataclass
class RouteDecision:
    path: str
    intent: str = "fact_qa"
    topic_changed: bool = True
    context_dependent: bool = False
    confidence: float = 0.7
    reason: str = "规则路由"
    reporting_level: str = "minimal"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteInput:
    query: str
    force_path: Optional[str] = None
    recent_turns: List[dict] = field(default_factory=list)
    memory_context: str = ""
    last_route: Optional[Dict[str, Any]] = None


class ContextAwareRouter:
    PAPER_KEYWORDS = [
        "论文", "paper", "arxiv", "摘要", "引言", "方法", "实验", "指标", "数据集",
        "相关工作", "引用", "reference", "citation", "作者", "结论", "消融", "开题", "大纲",
        "贡献", "局限", "不足", "创新点",
    ]
    SELF_RAG_KEYWORDS = [
        "最新", "当前", "现在", "2026", "验证", "可靠", "依据", "证据", "是否真实",
        "有没有支撑", "查证", "联网", "fresh", "verify", "reliable", "current",
    ]
    RESEARCH_KEYWORDS = [
        "研究综述", "文献综述", "研究方向", "研究空白", "开题报告", "跨论文", "多篇论文",
        "系统分析", "优化方案", "路线图", "技术路线", "架构设计", "设计", "拆解", "规划",
        "方案", "瓶颈", "升级", "roadmap", "survey", "research gap", "proposal",
    ]
    COMPLEX_KEYWORDS = [
        "分析", "对比", "比较", "如何", "为什么", "区别", "差异", "联系", "关系", "结合", "整合",
        "评价", "总结", "归纳", "推导", "论证", "上下游", "路径", "影响", "详细说明",
        "explain", "analyze", "compare", "difference", "relationship",
    ]
    FOLLOWUP_PATTERNS = [
        r"^(那|那么|继续|再|还有|这个|它|其|上面|刚才|前面)",
        r"(呢|怎么样|如何|为什么)$",
    ]

    def route(self, route_input: RouteInput) -> RouteDecision:
        query = route_input.query or ""
        force_path = self._normalize_path(route_input.force_path)
        if force_path:
            return RouteDecision(
                path=force_path,
                intent=f"force_{force_path}",
                topic_changed=False,
                context_dependent=False,
                confidence=1.0,
                reason="用户强制指定路径",
                reporting_level=self._reporting_level(force_path),
            )

        last_route = route_input.last_route or self._last_route_from_turns(route_input.recent_turns)
        followup = self._is_context_followup(query)

        if followup and last_route and self._normalize_path(last_route.get("path")):
            inherited = self._normalize_path(last_route.get("path"))
            intent = self._refine_followup_intent(query, inherited, last_route.get("intent", "followup"))
            return RouteDecision(
                path=inherited,
                intent=intent,
                topic_changed=False,
                context_dependent=True,
                confidence=0.86,
                reason="当前问题依赖上一轮上下文，继承上一轮路径",
                reporting_level=self._reporting_level(inherited),
            )

        features = self._features(query)
        scores = self._score_paths(query, features)
        path = max(scores, key=scores.get)
        confidence = self._confidence(scores)
        return RouteDecision(
            path=path,
            intent=self._intent_for_path(path, query, features),
            topic_changed=True,
            context_dependent=False,
            confidence=confidence,
            reason=self._route_reason(path, features),
            reporting_level=self._reporting_level(path),
            metadata={"features": features, "scores": scores},
        )

    def estimate_complexity(self, query: str) -> str:
        decision = self.route(RouteInput(query=query))
        return "simple" if decision.path == "fast" else "complex"

    def _features(self, query: str) -> Dict[str, Any]:
        lowered = query.lower()
        compare_terms = ["对比", "比较", "差异", "区别", "vs", "versus", "compare", "difference"]
        design_terms = ["设计", "架构", "方案", "路线", "技术路线", "拆解", "规划", "升级", "优化", "瓶颈", "roadmap", "proposal"]
        research_terms = self.RESEARCH_KEYWORDS
        verify_terms = self.SELF_RAG_KEYWORDS
        paper_terms = self.PAPER_KEYWORDS
        simple_terms = ["是什么", "定义", "什么意思", "介绍一下", "what is"]
        current_object_terms = ["这个结论", "该结论", "这个回答", "当前回答", "上述结论", "是否可靠", "可靠吗", "依据是什么", "证据是否", "有没有支撑"]
        multi_object = self._multi_object_signal(query)
        return {
            "has_research": self._contains_any(lowered, research_terms),
            "has_compare": self._contains_any(lowered, compare_terms),
            "has_design": self._contains_any(lowered, design_terms),
            "has_verify": self._contains_any(lowered, verify_terms),
            "has_paper": self._contains_any(lowered, paper_terms),
            "has_complex": self._contains_any(lowered, self.COMPLEX_KEYWORDS),
            "has_simple": self._contains_any(lowered, simple_terms),
            "current_object_verification": self._contains_any(lowered, current_object_terms),
            "multi_object": multi_object,
            "length": len(query),
        }

    def _score_paths(self, query: str, features: Dict[str, Any]) -> Dict[str, float]:
        scores = {"fast": 0.2, "pipeline": 0.25, "paper_assistant": 0.0, "self_rag": 0.0, "research": 0.0}
        if features["length"] < 30 and features["has_simple"]:
            scores["fast"] += 1.0
        elif features["length"] < 30:
            scores["fast"] += 0.45

        if features["has_complex"]:
            scores["pipeline"] += 0.55
        if features["has_compare"]:
            scores["pipeline"] += 0.2
        if features["multi_object"]:
            scores["pipeline"] += 0.2

        if features["has_paper"]:
            scores["paper_assistant"] += 0.65
            scores["fast"] = min(scores["fast"], 0.45)
        if features["has_paper"] and not (features["has_design"] or features["has_research"] or features["multi_object"] or features["has_verify"]):
            scores["paper_assistant"] += 0.35
        if features["has_verify"] and not (features["has_design"] or features["has_research"]):
            scores["paper_assistant"] -= 0.3

        if features["has_verify"]:
            scores["self_rag"] += 0.75
        if features["current_object_verification"]:
            scores["self_rag"] += 0.65
        if features["has_design"] or features["has_research"]:
            scores["self_rag"] -= 0.35

        if features["has_research"]:
            scores["research"] += 0.85
        if features["has_design"]:
            scores["research"] += 0.65
        if features["has_compare"] and features["multi_object"]:
            scores["research"] += 0.55
        if features["has_paper"] and (features["has_research"] or features["multi_object"]):
            scores["research"] += 0.35
        if features["has_verify"] and features["has_design"]:
            scores["research"] += 0.35
        if features["length"] > 45 and (features["has_complex"] or features["has_design"]):
            scores["research"] += 0.25

        if scores["research"] >= 0.9:
            scores["fast"] = min(scores["fast"], 0.25)
        return scores

    def _confidence(self, scores: Dict[str, float]) -> float:
        ranked = sorted(scores.values(), reverse=True)
        margin = ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0]
        return round(min(0.95, max(0.55, 0.62 + margin * 0.25)), 2)

    def _intent_for_path(self, path: str, query: str, features: Dict[str, Any]) -> str:
        lowered = query.lower()
        if path == "research":
            if features["has_design"]:
                return "research_design"
            return "research_planning"
        if path == "self_rag":
            return "verify_or_freshness"
        if path == "paper_assistant":
            return self._paper_intent(lowered)
        if path == "pipeline":
            return "complex_analysis"
        return "fact_qa" if features["has_simple"] or features["length"] < 30 else "general_qa"

    def _route_reason(self, path: str, features: Dict[str, Any]) -> str:
        if path == "research":
            return "识别为需要规划、比较、设计或研究综合的复杂任务"
        if path == "self_rag":
            return "识别为针对当前结论/回答的证据验证或时效性任务"
        if path == "paper_assistant":
            return "识别为单篇论文局部理解任务"
        if path == "pipeline":
            return "识别为普通知识图谱复杂分析/关系问题"
        return "简单事实问题走快速路径"

    def _multi_object_signal(self, query: str) -> bool:
        separators = ["、", ",", "，", " 和 ", "与", "及", "/", " vs ", " VS "]
        named_patterns = [r"[A-Za-z][A-Za-z0-9_-]{2,}"]
        named_count = sum(len(re.findall(pattern, query)) for pattern in named_patterns)
        return named_count >= 2 or any(sep in query for sep in separators)

    def _normalize_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        normalized = PATH_ALIASES.get(str(path), str(path))
        return normalized if normalized in VALID_PATHS else None

    def _contains_any(self, lowered_query: str, keywords: List[str]) -> bool:
        return any(keyword.lower() in lowered_query for keyword in keywords)

    def _is_context_followup(self, query: str) -> bool:
        stripped = (query or "").strip()
        if not stripped:
            return False
        if len(stripped) <= 12:
            return any(re.search(pattern, stripped) for pattern in self.FOLLOWUP_PATTERNS)
        return bool(re.search(r"(刚才|上面|前面|继续|这个|它|其)", stripped))

    def _last_route_from_turns(self, turns: List[dict]) -> Optional[Dict[str, Any]]:
        for turn in reversed(turns or []):
            if turn.get("role") == "assistant":
                route = turn.get("route_decision")
                if route:
                    return route
                if turn.get("path"):
                    return {"path": turn.get("path"), "intent": turn.get("intent", "followup")}
        return None

    def _refine_followup_intent(self, query: str, path: str, fallback: str) -> str:
        lowered = query.lower()
        if path == "paper_assistant":
            return self._paper_intent(lowered)
        if path == "self_rag" and self._contains_any(lowered, self.SELF_RAG_KEYWORDS):
            return "verify_or_freshness"
        return fallback or "followup"

    def _paper_intent(self, lowered_query: str) -> str:
        if any(token in lowered_query for token in ["实验", "指标", "数据集", "消融", "benchmark"]):
            return "paper_experiment"
        if any(token in lowered_query for token in ["方法", "模型", "算法", "框架", "公式"]):
            return "paper_method"
        if any(token in lowered_query for token in ["对比", "比较", "区别", "差异", "vs"]):
            return "paper_compare"
        if any(token in lowered_query for token in ["相关工作", "综述", "引用", "reference"]):
            return "paper_literature_review"
        if any(token in lowered_query for token in ["大纲", "开题", "提纲"]):
            return "paper_outline"
        if any(token in lowered_query for token in ["贡献", "创新点"]):
            return "paper_contribution"
        if any(token in lowered_query for token in ["局限", "不足", "限制"]):
            return "paper_limitation"
        return "paper_overview"

    def _reporting_level(self, path: str) -> str:
        return {
            "fast": "minimal",
            "pipeline": "normal",
            "paper_assistant": "normal",
            "self_rag": "verbose",
            "research": "verbose",
        }.get(path, "normal")


class ComplexityRouter(ContextAwareRouter):
    """Compatibility router for old call sites."""

    COMPLEX_KEYWORDS: List[str] = ContextAwareRouter.COMPLEX_KEYWORDS
