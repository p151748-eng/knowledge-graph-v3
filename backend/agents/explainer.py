"""
Explainer Agent: 术语通俗化解释。
将专业术语用通俗易懂的语言解释，并提供类比。
"""

from typing import Any, Dict, List
from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from models.schemas import ExplanationData


EXPLAINER_PROMPT = """你是一个知识科普专家。请将以下专业术语用通俗易懂的语言解释，并提供类比。

术语列表：
{terms}

请以JSON格式返回：
{{
  "explanations": [
    {{"term": "术语名称", "simple": "通俗解释（一句话）", "analogy": "类比说明"}}
  ],
  "glossary": {{
    "术语名称": "专业定义"
  }}
}}

要求：
- simple: 用最通俗的话解释，非技术人员也能理解
- analogy: 用生活中常见的例子来类比
- 返回纯JSON，不要包含任何其他文字
"""


class ExplainerAgent(BaseAgent):
    """术语通俗化 Agent"""

    def __init__(self, llm=None):
        super().__init__(
            name="Explainer",
            role="explainer",
            description="将专业术语通俗化解释"
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    def execute(self, context: AgentContext) -> AgentResult:
        """生成通俗解释"""
        rd = context.pipeline_data.retrieval_data
        if not rd:
            return AgentResult(
                success=False,
                output=None,
                message="无检索数据"
            )

        # 收集需要解释的术语
        entities = rd.entities[:8]  # 最多8个
        if not entities:
            context.pipeline_data.explanation_data = ExplanationData()
            return AgentResult(success=True, output={"explanations": []}, message="无可解释术语")

        terms = [f"- {e['name']} ({e.get('description', '')})" for e in entities]
        terms_text = "\n".join(terms)

        try:
            prompt = EXPLAINER_PROMPT.format(terms=terms_text)
            result = self.llm.complete_json(prompt, {})

            explanations = [
                {"term": e["term"], "simple": e["simple"], "analogy": e.get("analogy", "")}
                for e in result.get("explanations", [])
            ]
            glossary = result.get("glossary", {})

            explanation_data = ExplanationData(
                explanations=explanations,
                glossary=glossary,
            )
            context.pipeline_data.explanation_data = explanation_data

            return AgentResult(
                success=True,
                output={"explanations": explanations, "glossary": glossary},
                message=f"生成 {len(explanations)} 条通俗解释",
                confidence=0.7,
            )
        except Exception as e:
            # LLM 调用失败时返回空解释
            context.pipeline_data.explanation_data = ExplanationData()
            return AgentResult(
                success=True,
                output={"explanations": []},
                message=f"通俗解释生成失败: {str(e)}",
                confidence=0.5,
            )
