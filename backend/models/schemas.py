"""
内部业务数据结构，不直接暴露给 API。
用于 Agent 之间、Tool 之间传递的中间结果。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceGradeData:
    """CRAG 证据质量评估结果"""
    relevance_score: float = 0.0
    support_score: float = 0.0
    coverage_score: float = 0.0
    freshness_required: bool = False
    conflict_detected: bool = False
    sufficient: bool = False
    missing_aspects: List[str] = field(default_factory=list)
    next_action: str = "answer"
    reason: str = ""


@dataclass
class RetrievalAttemptData:
    """Self-RAG/CRAG 单轮检索记录"""
    round: int = 1
    query: str = ""
    strategy: Dict[str, Any] = field(default_factory=dict)
    retrieval: Dict[str, Any] = field(default_factory=dict)
    grade: Optional[EvidenceGradeData] = None
    source: str = "local"


@dataclass
class RetrievalData:
    """KGRetriever Agent 的输出"""
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    doc_chunks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExplanationData:
    """Explainer Agent 的输出"""
    explanations: List[Dict[str, str]] = field(default_factory=list)
    glossary: Dict[str, str] = field(default_factory=dict)


@dataclass
class IntegrationData:
    """Integrator Agent 的输出"""
    answer: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    key_points: List[str] = field(default_factory=list)
