"""
论文专家 Agent：负责不同论文任务的回答组织。
"""

from dataclasses import dataclass
from typing import Dict, Type

from agents.paper_task_router import PaperTaskPlan
from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from observability.langsmith_tracing import traceable


@dataclass
class PaperExpertInput:
    query: str
    plan: PaperTaskPlan
    context_text: str
    preferred_types: str


PAPER_EXPERT_PROMPT = """{role_instruction}

【用户问题】
{query}

【任务类型】
{task_type}

【回答风格】
{answer_style}

【优先证据类型】
{preferred_types}

【检索证据】
{context_text}

【回答要求】
1. 只使用检索证据中能支撑的内容，不要编造论文结论、指标或引用。
2. 如果证据不足，先说明不足，再给出基于现有证据的谨慎回答。
3. 尽量引用章节来源，例如 [abstract Introduction]、[method Method]、[experiment Results]。
4. 输出中文，结构清晰。

请直接返回答案。
"""


class BasePaperExpertAgent(BaseAgent):
    task_type = "overview"
    role_instruction = "你是论文参考助手，面向本科生和研究生，必须基于给定证据回答。"

    def __init__(self, llm=None):
        super().__init__(
            name=self.__class__.__name__,
            role=f"paper_{self.task_type}_expert",
            description="根据论文任务和证据组织回答",
        )
        from llm.manager import llm_manager
        self.llm = llm if llm is not None else llm_manager

    @traceable(name="paper_expert.execute", run_type="chain")
    def execute(self, context: AgentContext) -> AgentResult:
        payload = context.extra.get("paper_expert_input") if context.extra else None
        if not isinstance(payload, PaperExpertInput):
            return AgentResult(success=False, message="缺少论文专家输入")

        prompt = PAPER_EXPERT_PROMPT.format(
            role_instruction=self.role_instruction,
            query=payload.query,
            task_type=payload.plan.task_type,
            answer_style=payload.plan.answer_style,
            preferred_types=payload.preferred_types,
            context_text=payload.context_text or "（暂无足够论文证据）",
        )
        try:
            answer = self.llm.complete(prompt).content
        except Exception as exc:
            return AgentResult(success=False, message=f"论文专家回答生成失败: {exc}", errors=[str(exc)])
        return AgentResult(success=True, output={"answer": answer, "expert": self.role}, message="论文专家回答完成")


class PaperExplainerAgent(BasePaperExpertAgent):
    task_type = "overview"
    role_instruction = "你是论文概述专家。请按研究问题、核心方法、主要贡献、结论/局限组织回答。"


class MethodAnalysisAgent(BasePaperExpertAgent):
    task_type = "method"
    role_instruction = "你是方法分析专家。请按方法动机、关键模块、流程、与相关方法差异组织回答。"


class ExperimentAnalysisAgent(BasePaperExpertAgent):
    task_type = "experiment"
    role_instruction = "你是实验分析专家。请按数据集、指标、实验结论、可疑不足组织回答。"


class MethodCompareAgent(BasePaperExpertAgent):
    task_type = "compare"
    role_instruction = "你是方法对比专家。请用分点或表格比较目标、机制、证据和适用场景。"


class LiteratureReviewAgent(BasePaperExpertAgent):
    task_type = "literature_review"
    role_instruction = "你是相关工作综述专家。请按主题归纳研究脉络，不要伪造不存在的引用。"


class WritingAssistantAgent(BasePaperExpertAgent):
    task_type = "outline"
    role_instruction = "你是论文写作辅助专家。请给出可写成论文/开题报告的章节大纲，并标注每节依赖的证据类型。"


EXPERTS: Dict[str, Type[BasePaperExpertAgent]] = {
    "overview": PaperExplainerAgent,
    "method": MethodAnalysisAgent,
    "experiment": ExperimentAnalysisAgent,
    "compare": MethodCompareAgent,
    "literature_review": LiteratureReviewAgent,
    "outline": WritingAssistantAgent,
}


def create_paper_expert(task_type: str, llm=None) -> BasePaperExpertAgent:
    expert_cls = EXPERTS.get(task_type, PaperExplainerAgent)
    return expert_cls(llm)
