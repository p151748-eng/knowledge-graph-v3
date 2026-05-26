"""
AgentContext: Agent 执行上下文，包含 PipelineData。
用于在 3-Agent 流水线中传递数据。
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from models.schemas import EvidenceGradeData, IntegrationData, RetrievalAttemptData, RetrievalData, ExplanationData


@dataclass
class PipelineData:
    """流水线数据容器，在 Agent 间共享"""
    query: str = ""
    retrieval_data: Optional["RetrievalData"] = None
    explanation_data: Optional["ExplanationData"] = None
    integration_data: Optional["IntegrationData"] = None
    retrieval_attempts: List["RetrievalAttemptData"] = field(default_factory=list)
    evidence_grade: Optional["EvidenceGradeData"] = None
    web_evidence: List[Dict[str, Any]] = field(default_factory=list)
    answer_verification: Optional[Dict[str, Any]] = None


@dataclass
class AgentContext:
    """Agent 执行上下文"""
    pipeline_data: PipelineData = field(default_factory=PipelineData)
    extra: dict = field(default_factory=dict)
