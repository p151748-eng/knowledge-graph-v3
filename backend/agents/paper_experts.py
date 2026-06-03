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
    memory_context: str = ""
    web_context: str = ""


PAPER_EXPERT_PROMPT = """{role_instruction}

【用户问题】
{query}

【任务类型】
{task_type}

【回答风格】
{answer_style}

【优先证据类型】
{preferred_types}

【对话记忆/用户已选主题】
{memory_context}

【联网补充证据】
{web_context}

【检索证据】
{context_text}

【回答要求】
1. 只使用检索证据中能支撑的内容，不要编造论文结论、指标或引用。
2. 如果证据不足，先说明不足，再给出基于现有证据的谨慎回答。
3. 尽量引用章节来源，例如 [abstract Introduction]、[method Method]、[experiment Results]。
4. 如果用户明确说"选题三/选题二"等，必须优先使用【对话记忆/用户已选主题】中解析出的对应选题，不得改写成其他题目。
5. 输出中文，结构清晰。
6. 当【联网补充证据】中包含 [1]、[2] 等引用标记或 provider=ai4scholar 的论文证据时，必须在正文关键结论后标注对应引用，并在回答末尾增加"参考论文"或"引用来源"小节，按编号列出标题、作者、年份、链接。

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
            memory_context=payload.memory_context or "（无对话记忆）",
            web_context=payload.web_context or "（无联网补充证据）",
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


class OpeningReportAgent(BasePaperExpertAgent):
    task_type = "opening_report"
    role_instruction = """你是开题报告写作专家。必须基于用户已选题目、对话记忆、检索证据和联网补充内容，输出标准开题报告，而不是论文大纲。

请严格按以下模板组织：
一、课题名称
二、研究背景与研究意义（区分理论意义、实践意义）
三、国内外研究现状（按研究方向归纳，并指出不足）
四、研究目标与拟解决的关键问题
五、研究内容（3-5点，围绕用户选题，不得换题）
六、研究方法与技术路线（包含可执行步骤）
七、可行性分析
八、创新点
九、预期成果
十、进度安排
十一、参考文献与证据来源说明

写作规则：
1. 用户明确引用的选题必须原样作为核心研究对象。
2. 联网证据只能作为研究现状补充，不能覆盖用户选题定义。
3. 不要输出"第几章论文大纲"，不要只列章节标题。"""


class WritingAssistantAgent(BasePaperExpertAgent):
    task_type = "outline"
    role_instruction = "你是论文大纲写作辅助专家。请给出可写成论文的章节大纲，并标注每节依赖的证据类型；如果用户要开题报告，应改用标准开题报告结构。"


EXPERTS: Dict[str, Type[BasePaperExpertAgent]] = {
    "overview": PaperExplainerAgent,
    "method": MethodAnalysisAgent,
    "experiment": ExperimentAnalysisAgent,
    "compare": MethodCompareAgent,
    "literature_review": LiteratureReviewAgent,
    "opening_report": OpeningReportAgent,
    "outline": WritingAssistantAgent,
}


def create_paper_expert(task_type: str, llm=None) -> BasePaperExpertAgent:
    expert_cls = EXPERTS.get(task_type, PaperExplainerAgent)
    return expert_cls(llm)
