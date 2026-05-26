"""
Integrator Agent: 整合生成最终回答。
整合检索结果和通俗解释，生成结构化回答。
"""

from typing import Any
from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from models.schemas import IntegrationData


INTEGRATOR_PROMPT = """你是一个知识问答专家。基于以下信息回答用户问题。

【用户问题】
{query}

【对话记忆】
{memory_context}

【原始知识】
{context}

【通俗解释】
{explanations}

【要求】
1. 优先保持对话记忆中的当前焦点和上下文连贯性
2. 结合原始知识和通俗解释进行回答
3. 结构化输出，条理清晰
4. 如果有通俗解释，优先用通俗语言
5. 在回答末尾标注信息来源（如有）
6. 简洁明了，不要过度扩展

请直接返回回答内容。
"""


class IntegratorAgent(BaseAgent):
    """整合生成 Agent"""

    def __init__(self, llm=None):
        super().__init__(
            name="Integrator",
            role="integrator",
            description="整合检索结果和通俗解释生成最终回答"
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    def execute(self, context: AgentContext) -> AgentResult:
        """整合并生成回答"""
        rd = context.pipeline_data.retrieval_data
        ed = context.pipeline_data.explanation_data
        query = context.pipeline_data.query

        # 构建通俗解释文本
        exp_text = ""
        if ed and ed.explanations:
            exp_lines = []
            for e in ed.explanations:
                analogy = f"，比如{e['analogy']}" if e.get("analogy") else ""
                exp_lines.append(f"- {e['term']}: {e['simple']}{analogy}")
            exp_text = "\n".join(exp_lines)

        # 构建上下文
        context_text = rd.context_text if rd else ""
        if not context_text and rd and rd.entities:
            entities = rd.entities[:5]
            context_text = "\n".join([
                f"【{e['type']}】{e['name']}: {e.get('description', '')}"
                for e in entities
            ])

        try:
            prompt = INTEGRATOR_PROMPT.format(
                query=query,
                memory_context=(context.extra or {}).get("memory_context", "（无对话记忆）"),
                context=context_text or "（暂无相关知识）",
                explanations=exp_text or "（无通俗解释）",
            )
            answer = self.llm.complete(prompt).content

            # 构建来源
            sources = []
            if rd and rd.entities:
                for e in rd.entities[:5]:
                    sources.append({
                        "id": e["id"],
                        "name": e["name"],
                        "type": e.get("type", "entity"),
                        "description": e.get("description"),
                    })

            integration_data = IntegrationData(
                answer=answer,
                sources=sources,
                confidence=0.8,
                key_points=[],
            )
            context.pipeline_data.integration_data = integration_data

            return AgentResult(
                success=True,
                output={
                    "answer": answer,
                    "sources": sources,
                    "confidence": 0.8,
                },
                message="整合生成完成",
                confidence=0.8,
            )
        except Exception as e:
            return AgentResult(
                success=False,
                output=None,
                message=f"整合生成失败: {str(e)}",
                errors=[str(e)],
            )
