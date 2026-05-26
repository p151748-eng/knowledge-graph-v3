"""
AnswerVerifierAgent: 校验生成答案是否被本地/Web 证据支撑。
"""

from typing import Any, Dict, List

from core.agent import AgentResult, BaseAgent
from core.context import AgentContext


ANSWER_VERIFIER_PROMPT = """你是答案支撑性校验器，请判断答案是否被给定证据支撑，不要改写答案。

【用户问题】
{query}

【答案】
{answer}

【本地证据】
{local_context}

【联网证据】
{web_evidence}

请输出 JSON：
{{
  "supported": true或false,
  "support_score": 0.0到1.0,
  "unsupported_claims": ["未支撑断言"],
  "final_action": "answer | revise | refuse",
  "reason": "简短理由"
}}

如果答案包含证据中没有的信息，列入 unsupported_claims。不要输出 JSON 外的任何文字。
"""


class AnswerVerifierAgent(BaseAgent):
    """答案支撑性验证 Agent"""

    ACTIONS = {"answer", "revise", "refuse"}

    def __init__(self, llm=None):
        super().__init__(
            name="AnswerVerifier",
            role="answer_verifier",
            description="验证答案是否被检索证据支撑",
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    def execute(self, context: AgentContext) -> AgentResult:
        answer = context.extra.get("answer") or (context.pipeline_data.integration_data.answer if context.pipeline_data.integration_data else "")
        verification = self.verify(
            context.pipeline_data.query,
            answer,
            context.extra.get("local_context", ""),
            context.pipeline_data.web_evidence,
        )
        context.pipeline_data.answer_verification = verification
        return AgentResult(
            success=True,
            output=verification,
            message=verification.get("reason", "答案验证完成"),
            confidence=verification.get("support_score", 0.5),
        )

    def verify(self, query: str, answer: str, local_context: str, web_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        fallback = self._fallback(answer, local_context, web_evidence)
        try:
            prompt = ANSWER_VERIFIER_PROMPT.format(
                query=query,
                answer=answer,
                local_context=(local_context or "")[:5000],
                web_evidence=web_evidence[:5],
            )
            data = self.llm.complete_json(prompt, {})
            action = data.get("final_action") if data.get("final_action") in self.ACTIONS else fallback["final_action"]
            score = max(0.0, min(1.0, float(data.get("support_score", fallback["support_score"]))))
            return {
                "supported": bool(data.get("supported", fallback["supported"])),
                "support_score": score,
                "unsupported_claims": self._list(data.get("unsupported_claims")),
                "final_action": action,
                "reason": str(data.get("reason") or fallback["reason"]),
            }
        except Exception:
            return fallback

    def _fallback(self, answer: str, local_context: str, web_evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        supported = bool(answer.strip()) and bool(local_context.strip() or web_evidence)
        return {
            "supported": supported,
            "support_score": 0.7 if supported else 0.2,
            "unsupported_claims": [] if supported else ["缺少可用证据或答案为空"],
            "final_action": "answer" if supported else "refuse",
            "reason": "基于可用上下文的基础支撑性检查",
        }

    def _list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()][:5]
        return []
