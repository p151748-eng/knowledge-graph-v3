from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.orchestrator import WorkflowResult


@dataclass
class EvidenceItem:
    id: str
    source_type: str
    title: str = ""
    content: str = ""
    score: float = 0.0
    citation: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimItem:
    text: str
    supported: bool = False
    supporting_evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowState:
    query: str
    route_decision: Optional[Dict[str, Any]] = None
    context: Any = None
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    answer_draft: str = ""
    claims: List[ClaimItem] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    next_action: str = ""
    trace: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_evidence_from_retrieval(self, retrieval: Dict[str, Any]) -> None:
        seen = {item.id for item in self.evidence_items}
        for item in self._retrieval_items(retrieval):
            evidence = self._to_evidence_item(item)
            if evidence.id not in seen:
                self.evidence_items.append(evidence)
                seen.add(evidence.id)
        if retrieval.get("context_text") and not self.evidence_items:
            self.evidence_items.append(EvidenceItem(
                id="context:1",
                source_type="context",
                title="检索上下文",
                content=retrieval.get("context_text", ""),
                score=0.5,
                citation="context:1",
            ))

    def context_text(self, limit: int = 8) -> str:
        lines = []
        for item in self.evidence_items[:limit]:
            content = (item.content or "")[:700]
            lines.append(f"[{item.id}] {item.title}: {content}")
        return "\n".join(lines)

    def sources(self, limit: int = 8) -> List[Dict[str, Any]]:
        return [
            {
                "id": item.metadata.get("original_id") or item.id,
                "name": item.title or "证据",
                "type": item.source_type,
                "description": item.content[:160],
                "chunk_type": item.metadata.get("chunk_type"),
                "source": item.metadata.get("source"),
                "url": item.metadata.get("url"),
                "authors": item.metadata.get("authors"),
                "year": item.metadata.get("year"),
                "paper_id": item.metadata.get("paper_id"),
                "provider": item.metadata.get("provider"),
                "citation": item.citation,
            }
            for item in self.evidence_items[:limit]
        ]

    def evidence_dicts(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self.evidence_items]

    def claim_dicts(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self.claims]

    def to_workflow_result(self, path: str, confidence: float = 0.5, processing_time: str = "0.0s") -> WorkflowResult:
        return WorkflowResult(
            success=not self.errors,
            path=path,
            response=self.answer_draft,
            sources=self.sources(),
            confidence=confidence,
            processing_time=processing_time,
            message="; ".join(self.errors),
            metadata={
                **self.metadata,
                "evidence_items": self.evidence_dicts(),
                "claims": self.claim_dicts(),
                "citation_verification": self.verification,
                "graph_trace": self.trace,
            },
        )

    def _retrieval_items(self, retrieval: Dict[str, Any]) -> List[Dict[str, Any]]:
        merged = retrieval.get("merged") or []
        if merged:
            return merged
        items = []
        for key in ["bm25_hits", "semantic_hits", "graph_hits", "entity_hits", "web_evidence"]:
            items.extend(retrieval.get(key, []) or [])
        return items

    def _to_evidence_item(self, item: Dict[str, Any]) -> EvidenceItem:
        result_type = item.get("result_type") or item.get("type") or "document"
        original_id = item.get("chunk_id") or item.get("node_id") or item.get("edge_id") or item.get("paper_id") or item.get("id") or len(self.evidence_items) + 1
        evidence_id = f"{result_type}:{original_id}"
        title = item.get("paper_title") or item.get("title") or item.get("name") or item.get("description") or "证据"
        content = item.get("content") or item.get("description") or item.get("snippet") or title
        citation_label = item.get("citation") or evidence_id
        return EvidenceItem(
            id=evidence_id,
            source_type=result_type,
            title=str(title),
            content=str(content),
            score=float(item.get("total_score") or item.get("score") or item.get("quality_score") or 0.0),
            citation=citation_label,
            metadata={
                "original_id": original_id,
                "chunk_type": item.get("chunk_type") or item.get("section_type"),
                "source": item.get("source") or item.get("url"),
                "match_type": item.get("match_type"),
                "routes": item.get("routes", []),
                "authors": item.get("authors"),
                "year": item.get("year"),
                "paper_id": item.get("paper_id"),
                "provider": item.get("provider"),
                "url": item.get("url"),
            },
        )
