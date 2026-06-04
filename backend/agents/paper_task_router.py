"""
论文参考助手任务路由与检索偏好。
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List


@dataclass
class PaperTaskPlan:
    task_type: str = "paper_qa"
    answer_style: str = "evidence_qa"
    preferred_chunk_types: List[str] = field(default_factory=lambda: ["abstract", "introduction", "paragraph"])
    retrieval_override: Dict[str, Any] = field(default_factory=dict)
    reason: str = "默认论文问答"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "answer_style": self.answer_style,
            "preferred_chunk_types": self.preferred_chunk_types,
            "retrieval_override": self.retrieval_override,
            "reason": self.reason,
        }


class PaperTaskRouter:
    """根据论文参考任务选择 Agent 回答模式和检索偏好。"""

    TASKS = {
        "overview": {
            "answer_style": "paper_overview",
            "preferred": ["abstract", "introduction", "conclusion"],
            "override": {"bm25": True, "vector": True, "graph": False, "intent": "explain", "bm25_top_k": 10, "vector_top_k": 10, "graph_method": "none"},
            "reason": "论文概述优先摘要、引言和结论证据",
        },
        "method": {
            "answer_style": "method_explanation",
            "preferred": ["method", "equation", "code", "paragraph"],
            "override": {"bm25": True, "vector": True, "graph": False, "intent": "explain", "bm25_top_k": 12, "vector_top_k": 12, "graph_method": "none"},
            "reason": "方法解释优先方法、公式和代码证据",
        },
        "experiment": {
            "answer_style": "experiment_analysis",
            "preferred": ["experiment", "table", "paragraph"],
            "override": {"bm25": True, "vector": True, "graph": False, "intent": "explain", "bm25_top_k": 12, "vector_top_k": 10, "graph_method": "none"},
            "reason": "实验分析优先实验章节和表格证据",
        },
        "literature_review": {
            "answer_style": "literature_review",
            "preferred": ["related_work", "reference", "method", "abstract"],
            "override": {"bm25": True, "vector": True, "graph": True, "intent": "global_summary", "bm25_top_k": 14, "vector_top_k": 14, "graph_top_k": 8, "graph_method": "subgraph"},
            "reason": "相关工作综述需要相关工作、引用和方法证据",
        },
        "compare": {
            "answer_style": "method_comparison",
            "preferred": ["method", "experiment", "table"],
            "override": {"bm25": True, "vector": True, "graph": True, "intent": "relation", "bm25_top_k": 12, "vector_top_k": 12, "graph_top_k": 10, "graph_method": "path"},
            "reason": "方法对比需要方法、实验和关系路径证据",
        },
        "opening_report": {
            "answer_style": "opening_report",
            "preferred": ["abstract", "introduction", "related_work", "method", "experiment", "conclusion"],
            "override": {"bm25": True, "vector": True, "graph": True, "intent": "global_summary", "bm25_top_k": 16, "vector_top_k": 16, "graph_top_k": 8, "graph_method": "subgraph"},
            "reason": "开题报告需要按研究依据、内容、方案、创新点和进度组织",
        },
        "outline": {
            "answer_style": "writing_outline",
            "preferred": ["abstract", "introduction", "method", "experiment", "conclusion"],
            "override": {"bm25": True, "vector": True, "graph": False, "intent": "global_summary", "bm25_top_k": 12, "vector_top_k": 12, "graph_method": "none"},
            "reason": "论文大纲需要按论文主结构组织证据",
        },
    }

    KEYWORDS = {
        "literature_review": ["相关工作", "文献综述", "综述", "研究现状", "研究背景", "literature review", "related work", "survey"],
        "compare": ["对比", "比较", "区别", "不同", "差异", "优缺点", "vs", "versus", "compare", "difference"],
        "experiment": ["实验", "结果", "指标", "数据集", "消融", "benchmark", "bleu", "accuracy", "f1", "rouge", "dataset", "ablation"],
        "method": ["方法", "模型", "算法", "框架", "公式", "代码", "怎么做", "如何实现", "method", "model", "algorithm", "architecture"],
        "opening_report": ["开题报告", "开题", "研究方案", "课题申报", "proposal", "research proposal"],
        "outline": ["大纲", "论文结构", "写作思路", "章节安排", "提纲", "outline"],
        "overview": ["主要解决", "贡献", "创新点", "讲了什么", "总结一下", "概述", "是什么", "overview", "summary", "contribution"],
    }

    def route(self, query: str) -> PaperTaskPlan:
        query_lower = (query or "").lower()
        scores = {task: self._score(query_lower, words) for task, words in self.KEYWORDS.items()}
        if scores.get("opening_report", 0) > 0 and any(token in query_lower for token in ["开题报告", "研究方案", "课题申报", "research proposal", "proposal"]):
            task_type = "opening_report"
        elif scores.get("outline", 0) > 0 and any(token in query_lower for token in ["大纲", "提纲", "outline", "生成大纲", "章节安排"]):
            task_type = "outline"
        elif scores.get("literature_review", 0) > 0 and any(token in query_lower for token in ["综述", "研究现状", "相关工作", "文献综述"]):
            task_type = "literature_review"
        elif scores.get("compare", 0) > 0 and any(token in query_lower for token in ["区别", "不同", "差异", "对比", "比较", "vs", "versus", "compare"]):
            task_type = "compare"
        elif scores.get("experiment", 0) > 0 and any(token in query_lower for token in ["实验", "结果", "指标", "数据集", "消融", "benchmark", "bleu", "accuracy", "f1", "rouge", "dataset", "ablation"]):
            task_type = "experiment"
        else:
            task_type = max(scores, key=scores.get)
        if scores[task_type] <= 0:
            task_type = "overview" if self._looks_like_paper_query(query_lower) else "paper_qa"
        if task_type == "paper_qa":
            return PaperTaskPlan()
        config = self.TASKS[task_type]
        return PaperTaskPlan(
            task_type=task_type,
            answer_style=config["answer_style"],
            preferred_chunk_types=list(config["preferred"]),
            retrieval_override=dict(config["override"]),
            reason=config["reason"],
        )

    def _score(self, query: str, words: List[str]) -> int:
        return sum(1 for word in words if word.lower() in query)

    def _looks_like_paper_query(self, query: str) -> bool:
        return bool(re.search(r"论文|paper|arxiv|作者|摘要|引言|结论|reference|citation", query, re.I))
