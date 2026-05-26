import re
from typing import Any, Dict, List

from core.graph_state import ClaimItem, EvidenceItem


class CitationVerifier:
    def __init__(self, llm=None):
        self.llm = llm

    def verify(self, query: str, answer: str, evidence_items: List[EvidenceItem]) -> Dict[str, Any]:
        claims = self.extract_claims(answer)
        if not evidence_items:
            return {
                "supported": False,
                "support_score": 0.0,
                "citation_coverage": 0.0,
                "unsupported_claims": [claim.text for claim in claims] or ["缺少可用证据"],
                "supporting_evidence_ids": [],
                "claims": [claim.to_dict() for claim in claims],
                "final_action": "refuse",
                "reason": "没有证据可支撑答案",
            }

        supported_claims = []
        unsupported_claims = []
        supporting_ids = set()
        for claim in claims or [ClaimItem(text=answer[:180])]:
            matched = self._match_evidence(claim.text, evidence_items)
            if matched:
                claim.supported = True
                claim.supporting_evidence_ids = [item.id for item in matched[:3]]
                claim.confidence = min(0.95, 0.55 + 0.15 * len(matched))
                supporting_ids.update(claim.supporting_evidence_ids)
                supported_claims.append(claim)
            else:
                claim.supported = False
                claim.confidence = 0.2
                unsupported_claims.append(claim.text)

        total = max(len(claims), 1)
        coverage = len(supported_claims) / total
        supported = coverage >= 0.5 and bool(supporting_ids)
        return {
            "supported": supported,
            "support_score": round(coverage, 2),
            "citation_coverage": round(coverage, 2),
            "unsupported_claims": unsupported_claims[:5],
            "supporting_evidence_ids": sorted(supporting_ids),
            "claims": [(claim.to_dict()) for claim in (supported_claims + [c for c in claims if not c.supported])],
            "final_action": "answer" if supported else "revise",
            "reason": "答案断言已匹配到证据" if supported else "部分或全部断言缺少证据支撑",
        }

    def extract_claims(self, answer: str) -> List[ClaimItem]:
        parts = re.split(r"[。！？\n]+", answer or "")
        claims = []
        for part in parts:
            text = part.strip(" -：:;；")
            if len(text) >= 8:
                claims.append(ClaimItem(text=text[:240]))
            if len(claims) >= 6:
                break
        return claims

    def _match_evidence(self, claim: str, evidence_items: List[EvidenceItem]) -> List[EvidenceItem]:
        claim_terms = self._terms(claim)
        if not claim_terms:
            return evidence_items[:1] if claim.strip() else []
        matched = []
        for item in evidence_items:
            evidence_text = f"{item.title} {item.content}".lower()
            overlap = sum(1 for term in claim_terms if term.lower() in evidence_text)
            if overlap >= max(1, min(2, len(claim_terms) // 4)):
                matched.append(item)
        return matched

    def _terms(self, text: str) -> List[str]:
        terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[一-龥]{2,6}", text or "")
        stop = {"基于", "可以", "进行", "一个", "这个", "需要", "提出", "方向", "证据", "研究"}
        seen = set()
        result = []
        for term in terms:
            lowered = term.lower()
            if lowered in stop or lowered in seen:
                continue
            seen.add(lowered)
            result.append(term)
        return result[:12]
