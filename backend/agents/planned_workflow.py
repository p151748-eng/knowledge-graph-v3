"""
受控研究工作流：规划、检索、观察、综合与证据验证。
"""

from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Dict, List, Optional

from agents.citation_verifier import CitationVerifier
from agents.paper_assistant import PaperAssistantAgent
from agents.web_verifier import WebSearchVerifierAgent
from core.agent import AgentResult
from core.context import AgentContext
from core.graph_state import ClaimItem, WorkflowState
from core.orchestrator import BaseWorkflow, WorkflowResult
from core.state_graph import GraphEdge, GraphNode, StateGraphRunner
from models.schemas import EvidenceGradeData
from observability.langsmith_tracing import traceable
from tools.hybrid_search import HybridSearchTool


ALLOWED_RESEARCH_TASKS = {
    "retrieve_papers",
    "retrieve_kg_context",
    "summarize_evidence",
    "summarize_method",
    "compare_methods",
    "extract_experiments",
    "find_research_gap",
    "generate_outline",
    "generate_proposal",
    "verify_claims",
}

ALLOWED_RESEARCH_ACTIONS = {
    "classify_research_intent",
    "decompose_question",
    "search_local_knowledge",
    "search_local_papers",
    "search_academic_or_web",
    "analyze_single_paper",
    "synthesize_research",
    "verify_claims",
    "targeted_repair_search",
    "final_answer",
    "boundary_handoff",
    "memory_first_answer",
    "skip_optional_tools",
}

RESEARCH_TOOL_GRAPH = {
    "memory_guard": ["memory_first_answer", "planner"],
    "memory_first_answer": ["finalize"],
    "planner": ["decompose", "finalize"],
    "decompose": ["action_policy"],
    "action_policy": ["local_search", "external_search", "paper_analysis", "observation"],
    "local_search": ["external_search", "paper_analysis", "observation"],
    "external_search": ["paper_analysis", "observation"],
    "paper_analysis": ["observation"],
    "observation": ["synthesis"],
    "synthesis": ["citation_verifier"],
    "citation_verifier": ["targeted_repair", "finalize"],
    "targeted_repair": ["synthesis", "finalize"],
    "finalize": [],
}

RESEARCH_INTENT_TOOLS = {
    "memory_followup": ["memory_context"],
    "direction_exploration": ["HybridSearchTool", "WebSearchVerifierAgent"],
    "literature_review": ["HybridSearchTool", "WebSearchVerifierAgent"],
    "method_comparison": ["HybridSearchTool", "PaperAssistantAgent", "CitationVerifier"],
    "gap_analysis": ["HybridSearchTool", "WebSearchVerifierAgent", "CitationVerifier"],
    "proposal_design": ["HybridSearchTool", "WebSearchVerifierAgent", "CitationVerifier"],
}

MEMORY_FIRST_MARKERS = [
    "刚才", "之前", "前文", "上面", "继续", "回到", "我们确定", "已确定",
    "这个选题", "该选题", "这个方案", "这个研究", "不看前文", "刚刚",
]

NOT_RESEARCH_SIMPLE_TERMS = ["是什么", "定义", "什么意思", "介绍一下", "what is"]


@dataclass
class PlanningBudget:
    max_subtasks: int = 8
    max_retrieval_calls: int = 5
    max_llm_calls: int = 8
    max_web_calls: int = 1
    max_runtime_seconds: int = 60


@dataclass
class ResearchBudget:
    max_steps: int = 16
    max_local_searches: int = 2
    max_web_searches: int = 1
    max_paper_analyses: int = 1
    max_runtime_seconds: int = 60


@dataclass
class ResearchAction:
    step: int
    action: str
    query: str = ""
    reason: str = ""
    tool_name: str = ""
    observation_summary: str = ""
    evidence_count: int = 0
    status: str = "pending"
    node: str = ""
    next_node: str = ""
    intent: str = ""
    allowed_tools: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchToolSpec:
    action: str
    tool_name: str
    node: str
    writes_to: str
    precondition: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlannedTask:
    id: str
    type: str
    query: str = ""
    target: str = ""
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    goal: str
    tasks: List[PlannedTask]
    budget: PlanningBudget = field(default_factory=PlanningBudget)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "tasks": [asdict(task) for task in self.tasks],
            "budget": asdict(self.budget),
        }


RESEARCH_TOOL_SPECS = {
    "search_local_knowledge": ResearchToolSpec("search_local_knowledge", "HybridSearchTool", "local_search", "evidence_items", "intent 需要本地知识库证据"),
    "search_local_papers": ResearchToolSpec("search_local_papers", "HybridSearchTool", "local_search", "evidence_items", "intent 需要论文或文献证据"),
    "search_academic_or_web": ResearchToolSpec("search_academic_or_web", "WebSearchVerifierAgent", "external_search", "evidence_items", "用户要求联网/最新资料或验证后证据不足"),
    "analyze_single_paper": ResearchToolSpec("analyze_single_paper", "PaperAssistantAgent", "paper_analysis", "evidence_items", "用户明确单篇论文对象"),
    "verify_claims": ResearchToolSpec("verify_claims", "CitationVerifier", "citation_verifier", "citation_verification", "最终答案生成后必须验证"),
}

RESEARCH_PLANNER_PROMPT = """你是研究型知识库任务规划器。请把用户目标拆成受控子任务，只返回 JSON。

【用户目标】
{query}

【允许任务类型】
{allowed_tasks}

【预算】
最多 8 个子任务，最多 5 次检索，最多 8 次 LLM，总是包含 verify_claims。

返回格式：
{{
  "goal": "...",
  "tasks": [
    {{"id": "t1", "type": "retrieve_papers", "query": "...", "target": "", "depends_on": [], "params": {{}}}}
  ]
}}
"""


class ResearchWorkflow(BaseWorkflow):
    path = "research"

    @traceable(name="research_workflow.execute", run_type="chain")
    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        memory_context = (context.extra or {}).get("memory_context", "")
        query = self._contextual_query(context.pipeline_data.query, context, decision)
        if self._should_answer_from_memory(query, memory_context, decision):
            answer = self._answer_from_memory(query, memory_context)
            elapsed = time.time() - start
            action = ResearchAction(
                step=1,
                action="memory_first_answer",
                query=query,
                reason="当前问题依赖前文研究方案，优先使用对话记忆",
                tool_name="memory_context",
                observation_summary="已基于对话记忆生成回答",
                evidence_count=0,
                status="completed",
                node="memory_first_answer",
                next_node="finalize",
                intent="memory_followup",
                allowed_tools=RESEARCH_INTENT_TOOLS["memory_followup"],
            )
            return WorkflowResult(
                success=not answer.startswith("[错误]"),
                path="research",
                response=answer,
                confidence=0.82 if not answer.startswith("[错误]") else 0.0,
                processing_time=f"{elapsed:.1f}s",
                metadata={
                    "memory_first": True,
                    "research_intent": "memory_followup",
                    "research_actions": [action.to_dict()],
                    "tool_graph": self._tool_graph_metadata(),
                    "graph_trace": [{"node": "memory_guard", "next_action": "memory_first_answer"}, {"node": "memory_first_answer", "next_action": "finalize"}],
                },
            )

        graph_state = WorkflowState(
            query=query,
            route_decision=decision.to_dict() if decision else None,
            context=context,
        )
        graph_state.metadata["started_at"] = start
        graph_state.metadata["research_budget"] = asdict(ResearchBudget())
        graph_state.metadata["research_actions"] = []
        graph_state.metadata["tool_graph"] = self._tool_graph_metadata()
        graph = StateGraphRunner(
            nodes=[
                GraphNode("memory_guard", self._memory_guard_node),
                GraphNode("planner", self._planner_node),
                GraphNode("decompose", self._decompose_node),
                GraphNode("action_policy", self._action_policy_node),
                GraphNode("local_search", self._local_search_node),
                GraphNode("external_search", self._external_search_node),
                GraphNode("paper_analysis", self._paper_analysis_node),
                GraphNode("observation", self._observation_node),
                GraphNode("synthesis", self._synthesis_node),
                GraphNode("citation_verifier", self._citation_verifier_node),
                GraphNode("targeted_repair", self._targeted_repair_node),
                GraphNode("finalize", self._finalize_node),
            ],
            edges=[
                GraphEdge("memory_guard", "planner", lambda state: not state.errors),
                GraphEdge("planner", "finalize", lambda state: state.next_action == "finalize"),
                GraphEdge("planner", "decompose", lambda state: state.next_action == "decompose" and not state.errors),
                GraphEdge("decompose", "action_policy", lambda state: not state.errors),
                GraphEdge("action_policy", "local_search", lambda state: state.next_action == "local_search" and not state.errors),
                GraphEdge("action_policy", "external_search", lambda state: state.next_action == "external_search" and not state.errors),
                GraphEdge("action_policy", "paper_analysis", lambda state: state.next_action == "paper_analysis" and not state.errors),
                GraphEdge("action_policy", "observation", lambda state: state.next_action == "observation" and not state.errors),
                GraphEdge("local_search", "external_search", lambda state: state.next_action == "external_search" and not state.errors),
                GraphEdge("local_search", "paper_analysis", lambda state: state.next_action == "paper_analysis" and not state.errors),
                GraphEdge("local_search", "observation", lambda state: state.next_action == "observation" and not state.errors),
                GraphEdge("external_search", "paper_analysis", lambda state: state.next_action == "paper_analysis" and not state.errors),
                GraphEdge("external_search", "observation", lambda state: state.next_action == "observation" and not state.errors),
                GraphEdge("paper_analysis", "observation", lambda state: not state.errors),
                GraphEdge("observation", "synthesis", lambda state: not state.errors),
                GraphEdge("synthesis", "citation_verifier", lambda state: not state.errors),
                GraphEdge("citation_verifier", "targeted_repair", lambda state: state.next_action == "targeted_repair" and not state.errors),
                GraphEdge("citation_verifier", "finalize", lambda state: not state.errors),
                GraphEdge("targeted_repair", "synthesis", lambda state: state.next_action == "synthesis" and not state.errors),
                GraphEdge("targeted_repair", "finalize"),
            ],
            start_node="memory_guard",
            max_steps=ResearchBudget().max_steps,
        )
        graph_state = graph.run(graph_state)
        elapsed = time.time() - start
        confidence = graph_state.verification.get("support_score", graph_state.verification.get("confidence", 0.5))
        result = graph_state.to_workflow_result("research", confidence=confidence, processing_time=f"{elapsed:.1f}s")
        if graph_state.errors and not result.response:
            result.response = f"[错误] 研究工作流执行失败: {'; '.join(graph_state.errors)}"
        return result

    async def run_async(self, context: AgentContext, decision=None):
        start = time.time()
        yield {"type": "status", "agent": "ResearchPlanner", "step": "规划研究子任务", "elapsed": 0.0}
        result = self.run(context, decision)

        status_by_node = {
            "memory_guard": ("ResearchWorkflow", "判断研究任务边界"),
            "planner": ("ResearchPlanner", "拆解研究计划"),
            "decompose": ("ResearchWorkflow", "映射工具动作"),
            "action_policy": ("ResearchWorkflow", "选择下一步工具"),
            "local_search": ("ResearchWorkflow", "检索本地论文和知识库"),
            "external_search": ("WebVerifier", "联网补充证据"),
            "paper_analysis": ("PaperAssistant", "调用论文专家"),
            "observation": ("ResearchWorkflow", "整理证据观察"),
            "synthesis": ("ResearchWorkflow", "综合研究结果"),
            "citation_verifier": ("CitationVerifier", "验证研究结论"),
            "targeted_repair": ("RetrievalRepair", "补充缺失证据"),
            "finalize": ("ResearchWorkflow", "整理最终回答"),
        }
        for trace in result.metadata.get("graph_trace", []):
            node = trace.get("node", "")
            agent, step = status_by_node.get(node, ("ResearchWorkflow", node or "执行研究步骤"))
            yield {"type": "status", "agent": agent, "step": step, "elapsed": time.time() - start}

        if result.sources:
            yield {"type": "sources", "data": result.sources}
        for char in result.response:
            yield {"type": "delta", "content": char}
        yield {"type": "metrics", "path": "research", "processing_time": result.processing_time, "confidence": result.confidence, **result.metadata}

    def _memory_guard_node(self, state: WorkflowState) -> WorkflowState:
        state.next_action = "planner"
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="classify_research_intent",
            query=state.query,
            reason="进入研究边界判断",
            tool_name="ResearchWorkflow",
            observation_summary="问题将按研究任务边界继续处理",
            status="completed",
            node="memory_guard",
            next_node="planner",
            intent=self._classify_research_intent(state.query),
            allowed_tools=[],
        ))
        return state

    @traceable(name="research_workflow.planner", run_type="chain")
    def _planner_node(self, state: WorkflowState) -> WorkflowState:
        intent = self._classify_research_intent(state.query)
        state.metadata["research_intent"] = intent
        if intent == "not_research":
            state.answer_draft = self._boundary_handoff(state.query)
            state.metadata["research_plan"] = ExecutionPlan(goal=state.query, tasks=[]).to_dict()
            self._record_action(state, ResearchAction(
                step=self._next_action_step(state),
                action="boundary_handoff",
                query=state.query,
                reason="问题不属于研究工作流能力边界",
                tool_name="ResearchWorkflow",
                observation_summary="未调用检索或外部工具",
                status="completed",
                node="planner",
                next_node="finalize",
                intent=intent,
                allowed_tools=[],
            ))
            state.next_action = "finalize"
            state.errors.append("not_research")
            return state
        plan = self._validate_plan(self._make_plan(state.query))
        state.metadata["research_plan"] = plan.to_dict()
        state.metadata["plan"] = plan
        state.metadata["allowed_tools"] = RESEARCH_INTENT_TOOLS.get(intent, [])
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="decompose_question",
            query=state.query,
            reason=f"识别为 {intent}，生成受控研究计划",
            tool_name="ResearchPlanner",
            observation_summary=f"生成 {len(plan.tasks)} 个子任务，最终包含 verify_claims",
            status="completed",
            node="planner",
            next_node="decompose",
            intent=intent,
            allowed_tools=state.metadata["allowed_tools"],
        ))
        state.next_action = "decompose"
        return state

    def _decompose_node(self, state: WorkflowState) -> WorkflowState:
        plan = state.metadata["plan"]
        actions = self._actions_for_plan(plan, state.metadata.get("research_intent", "direction_exploration"), state.query)
        state.metadata["planned_actions"] = actions
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="decompose_question",
            query=state.query,
            reason="将研究计划映射为白名单 action 队列",
            tool_name="ResearchWorkflow",
            observation_summary="; ".join(actions) or "无工具 action",
            status="completed",
            node="decompose",
            next_node="action_policy",
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = "action_policy"
        return state

    def _action_policy_node(self, state: WorkflowState) -> WorkflowState:
        actions = state.metadata.get("planned_actions", [])
        if "search_local_papers" in actions or "search_local_knowledge" in actions:
            state.next_action = "local_search"
        elif "search_academic_or_web" in actions:
            state.next_action = "external_search"
        elif "analyze_single_paper" in actions:
            state.next_action = "paper_analysis"
        else:
            state.next_action = "observation"
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="skip_optional_tools" if state.next_action == "observation" else "decompose_question",
            query=state.query,
            reason="根据 intent、预算和工具拓扑选择下一节点",
            tool_name="ResearchActionPolicy",
            observation_summary=f"next_node={state.next_action}",
            status="completed",
            node="action_policy",
            next_node=state.next_action,
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        return state

    @traceable(name="research_workflow.local_search", run_type="retriever")
    def _local_search_node(self, state: WorkflowState) -> WorkflowState:
        plan = state.metadata["plan"]
        retrieval = self._retrieve_for_plan(plan)
        state.metadata["retrieval"] = retrieval
        before = len(state.evidence_items)
        state.add_evidence_from_retrieval(retrieval)
        added = len(state.evidence_items) - before
        action = "search_local_papers" if self._intent_needs_papers(state.metadata.get("research_intent", ""), state.query) else "search_local_knowledge"
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action=action,
            query=self._retrieval_query_for_plan(plan),
            reason="本地证据是研究综合的默认依据",
            tool_name="HybridSearchTool",
            observation_summary=self._retrieval_observation(retrieval),
            evidence_count=added,
            status="completed",
            node="local_search",
            next_node=self._next_after_local_search(state),
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = self._next_after_local_search(state)
        return state

    @traceable(name="research_workflow.external_search", run_type="retriever")
    def _external_search_node(self, state: WorkflowState) -> WorkflowState:
        if not self._should_run_external_search(state):
            self._record_action(state, ResearchAction(
                step=self._next_action_step(state),
                action="skip_optional_tools",
                query=state.query,
                reason="未满足联网触发条件",
                tool_name="WebSearchVerifierAgent",
                observation_summary="跳过联网补证",
                evidence_count=0,
                status="skipped",
                node="external_search",
                next_node=self._next_after_external_search(state),
                intent=state.metadata.get("research_intent", ""),
                allowed_tools=state.metadata.get("allowed_tools", []),
            ))
            state.next_action = self._next_after_external_search(state)
            return state
        try:
            web_items = self._search_web_evidence(state.query, ["研究任务需要外部证据"], max_results=6)
            for index, item in enumerate(web_items, start=1):
                item.setdefault("citation", f"[{index}]")
            retrieval = state.metadata.get("retrieval") or {}
            retrieval.setdefault("merged", [])
            retrieval["merged"] = web_items + retrieval["merged"]
            retrieval["web_evidence"] = web_items
            retrieval["web_search_provider"] = "mixed"
            state.metadata["retrieval"] = retrieval
            before = len(state.evidence_items)
            state.add_evidence_from_retrieval({"web_evidence": web_items})
            status = "completed" if web_items else "skipped"
            summary = f"接受 {len(web_items)} 条外部证据" if web_items else "未找到可接受外部证据"
            added = len(state.evidence_items) - before
        except Exception as exc:
            status = "failed"
            summary = f"联网补证失败：{exc}"
            added = 0
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="search_academic_or_web",
            query=state.query,
            reason=self._external_search_reason(state),
            tool_name="WebSearchVerifierAgent",
            observation_summary=summary,
            evidence_count=added,
            status=status,
            node="external_search",
            next_node=self._next_after_external_search(state),
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = self._next_after_external_search(state)
        return state

    @traceable(name="research_workflow.paper_analysis", run_type="chain")
    def _paper_analysis_node(self, state: WorkflowState) -> WorkflowState:
        if not self._should_run_paper_analysis(state):
            self._record_action(state, ResearchAction(
                step=self._next_action_step(state),
                action="skip_optional_tools",
                query=state.query,
                reason="没有明确单篇论文对象",
                tool_name="PaperAssistantAgent",
                observation_summary="跳过单篇论文专家",
                status="skipped",
                node="paper_analysis",
                next_node="observation",
                intent=state.metadata.get("research_intent", ""),
                allowed_tools=state.metadata.get("allowed_tools", []),
            ))
            state.next_action = "observation"
            return state
        try:
            paper_context = AgentContext(pipeline_data=state.context.pipeline_data, extra=state.context.extra if state.context else {})
            result = PaperAssistantAgent(self.db, self.llm).run(paper_context)
            output = result.output or {}
            sources = output.get("sources", []) if result.success else []
            before = len(state.evidence_items)
            state.add_evidence_from_retrieval({"merged": [{**source, "result_type": source.get("type", "paper_analysis"), "content": source.get("description") or source.get("name", "")} for source in sources]})
            status = "completed" if result.success else "failed"
            summary = output.get("answer", result.message)[:180] if result.success else result.message
            added = len(state.evidence_items) - before
        except Exception as exc:
            status = "failed"
            summary = f"论文专家调用失败：{exc}"
            added = 0
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="analyze_single_paper",
            query=state.query,
            reason="用户问题包含明确单篇论文对象，需要论文专家提取证据",
            tool_name="PaperAssistantAgent",
            observation_summary=summary,
            evidence_count=added,
            status=status,
            node="paper_analysis",
            next_node="observation",
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = "observation"
        return state

    def _observation_node(self, state: WorkflowState) -> WorkflowState:
        state.metadata["observation_summary"] = self._evidence_observation(state)
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="synthesize_research",
            query=state.query,
            reason="证据收集结束，进入研究综合",
            tool_name="ResearchWorkflow",
            observation_summary=state.metadata["observation_summary"],
            evidence_count=len(state.evidence_items),
            status="completed",
            node="observation",
            next_node="synthesis",
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = "synthesis"
        return state

    @traceable(name="research_workflow.synthesis", run_type="chain")
    def _synthesis_node(self, state: WorkflowState) -> WorkflowState:
        plan = state.metadata.get("plan") or ExecutionPlan(goal=state.query, tasks=[])
        state.answer_draft = self._synthesize(state.query, plan, state)
        state.next_action = "verify_citations"
        return state

    @traceable(name="research_workflow.citation_verifier", run_type="chain")
    def _citation_verifier_node(self, state: WorkflowState) -> WorkflowState:
        verification = CitationVerifier(self.llm).verify(state.query, state.answer_draft, state.evidence_items)
        state.verification = verification
        state.claims = [
            ClaimItem(
                text=item.get("text", ""),
                supported=bool(item.get("supported", False)),
                supporting_evidence_ids=item.get("supporting_evidence_ids", []),
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in verification.get("claims", [])
        ]
        state.metadata["answer_verification"] = {
            "supported": verification.get("supported", False),
            "support_score": verification.get("support_score", 0.0),
            "unsupported_claims": verification.get("unsupported_claims", []),
            "final_action": verification.get("final_action", "revise"),
            "reason": verification.get("reason", ""),
        }
        needs_repair = self._should_targeted_repair(state, verification)
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="verify_claims",
            query=state.query,
            reason="最终研究结论必须经过证据支撑验证",
            tool_name="CitationVerifier",
            observation_summary=verification.get("reason", ""),
            evidence_count=len(state.evidence_items),
            status="completed",
            node="citation_verifier",
            next_node="targeted_repair" if needs_repair else "finalize",
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = "targeted_repair" if needs_repair else "finalize"
        return state

    @traceable(name="research_workflow.targeted_repair", run_type="retriever")
    def _targeted_repair_node(self, state: WorkflowState) -> WorkflowState:
        state.metadata["targeted_repair_attempted"] = True
        missing = state.verification.get("unsupported_claims") or []
        if not missing:
            state.next_action = "finalize"
            return state
        try:
            repair_query = f"{state.query}\n需要补证：{'；'.join(missing[:3])}"
            retrieval = HybridSearchTool(self.db, self.llm).execute(repair_query, top_k=6)
            before = len(state.evidence_items)
            state.add_evidence_from_retrieval(retrieval)
            added = len(state.evidence_items) - before
            state.metadata["repair_retrieval"] = retrieval
            status = "completed" if added else "skipped"
            summary = self._retrieval_observation(retrieval) if added else "补充检索未增加新证据"
        except Exception as exc:
            added = 0
            status = "failed"
            summary = f"补充检索失败：{exc}"
        self._record_action(state, ResearchAction(
            step=self._next_action_step(state),
            action="targeted_repair_search",
            query=state.query,
            reason="验证发现关键断言缺少证据，预算允许一次补充检索",
            tool_name="HybridSearchTool",
            observation_summary=summary,
            evidence_count=added,
            status=status,
            node="targeted_repair",
            next_node="synthesis" if added else "finalize",
            intent=state.metadata.get("research_intent", ""),
            allowed_tools=state.metadata.get("allowed_tools", []),
        ))
        state.next_action = "synthesis" if added else "finalize"
        return state

    def _finalize_node(self, state: WorkflowState) -> WorkflowState:
        state.metadata.pop("plan", None)
        state.metadata.pop("retrieval", None)
        state.metadata.pop("repair_retrieval", None)
        if "not_research" in state.errors:
            state.errors = [error for error in state.errors if error != "not_research"]
        state.next_action = "done"
        return state

    def _classify_research_intent(self, query: str) -> str:
        lowered = (query or "").lower()
        if any(marker in query for marker in MEMORY_FIRST_MARKERS):
            return "memory_followup"
        if self._looks_like_pure_verification(query):
            return "not_research"
        if self._looks_like_single_paper_reading(query):
            return "not_research"
        if len(query or "") < 30 and any(term in lowered for term in NOT_RESEARCH_SIMPLE_TERMS):
            return "not_research"
        if any(term in lowered for term in ["文献综述", "研究综述", "综述", "研究现状", "相关工作", "survey", "literature review"]):
            return "literature_review"
        if any(term in lowered for term in ["对比", "比较", "差异", "区别", "vs", "compare", "difference"]):
            return "method_comparison"
        if any(term in lowered for term in ["研究空白", "空白", "创新点", "gap", "underexplored"]):
            return "gap_analysis"
        if any(term in lowered for term in ["开题", "研究方案", "技术路线", "路线图", "架构设计", "实验设计", "proposal", "roadmap"]):
            return "proposal_design"
        if any(term in lowered for term in ["研究方向", "研究点", "选题", "可做", "方向", "探索"]):
            return "direction_exploration"
        return "direction_exploration" if self._looks_research_like(query) else "not_research"

    def _looks_research_like(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in ["研究", "论文", "文献", "方法", "rag", "graphrag", "self-rag", "crag", "agent"])

    def _looks_like_pure_verification(self, query: str) -> bool:
        lowered = (query or "").lower()
        verify_terms = ["可靠吗", "是否可靠", "验证", "查证", "证据支撑", "有没有支撑"]
        research_terms = ["研究空白", "研究方案", "技术路线", "文献综述", "开题"]
        return any(term in lowered for term in verify_terms) and not any(term in lowered for term in research_terms)

    def _looks_like_single_paper_reading(self, query: str) -> bool:
        lowered = (query or "").lower()
        single_paper = any(term in lowered for term in ["这篇论文", "该论文", "这篇paper", "this paper"])
        reading_terms = ["方法是什么", "实验", "贡献", "局限", "总结", "摘要", "讲了什么", "怎么做"]
        compare_or_research = any(term in lowered for term in ["比较", "对比", "研究空白", "技术路线", "开题", "方案"])
        return single_paper and any(term in lowered for term in reading_terms) and not compare_or_research

    def _boundary_handoff(self, query: str) -> str:
        if self._looks_like_single_paper_reading(query):
            return "这个问题更适合走论文助手 paper_assistant：它专门处理单篇论文的方法、实验、贡献和局限分析。"
        if self._looks_like_pure_verification(query):
            return "这个问题更适合走 self_rag：它专门处理结论可靠性、证据支撑和联网查证。"
        return "这个问题不属于研究工作流的能力边界，建议使用 fast 或 pipeline 路径处理。"

    def _actions_for_plan(self, plan: ExecutionPlan, intent: str, query: str) -> List[str]:
        actions: List[str] = []
        if intent in {"literature_review", "method_comparison", "gap_analysis", "proposal_design"}:
            actions.append("search_local_papers")
        elif intent == "direction_exploration":
            actions.append("search_local_knowledge")
        if self._should_plan_external_search(intent, query):
            actions.append("search_academic_or_web")
        if self._should_analyze_single_paper_from_query(query, intent):
            actions.append("analyze_single_paper")
        actions.extend(["synthesize_research", "verify_claims", "final_answer"])
        return [action for action in actions if action in ALLOWED_RESEARCH_ACTIONS]

    def _should_plan_external_search(self, intent: str, query: str) -> bool:
        if self._web_search_requested(query):
            return True
        if intent == "literature_review" and self._research_needs_fresh_evidence(query):
            return True
        if any(term in (query or "") for term in ["最新", "近年", "2025", "2026", "当前"]):
            return True
        return False

    def _should_analyze_single_paper_from_query(self, query: str, intent: str) -> bool:
        if intent != "method_comparison":
            return False
        lowered = (query or "").lower()
        return any(term in lowered for term in ["这篇论文", "该论文", "某篇论文", "论文a", "论文 a", "已入库论文"])

    def _intent_needs_papers(self, intent: str, query: str) -> bool:
        return intent in {"literature_review", "method_comparison", "gap_analysis", "proposal_design"} or any(term in (query or "") for term in ["论文", "文献"])

    def _next_after_local_search(self, state: WorkflowState) -> str:
        actions = state.metadata.get("planned_actions", [])
        if "search_academic_or_web" in actions or self._local_evidence_insufficient_for_web(state):
            return "external_search"
        if "analyze_single_paper" in actions:
            return "paper_analysis"
        return "observation"

    def _next_after_external_search(self, state: WorkflowState) -> str:
        if "analyze_single_paper" in state.metadata.get("planned_actions", []):
            return "paper_analysis"
        return "observation"

    def _should_run_external_search(self, state: WorkflowState) -> bool:
        if "search_academic_or_web" not in state.metadata.get("planned_actions", []) and not self._local_evidence_insufficient_for_web(state):
            return False
        if self._count_actions(state, "search_academic_or_web") >= ResearchBudget().max_web_searches:
            return False
        return True

    def _local_evidence_insufficient_for_web(self, state: WorkflowState) -> bool:
        intent = state.metadata.get("research_intent", "")
        if intent not in {"literature_review", "gap_analysis", "proposal_design"}:
            return False
        if len(state.evidence_items) == 0:
            return True
        if self._research_needs_fresh_evidence(state.query) and len(state.evidence_items) < 3:
            return True
        return False

    def _should_run_paper_analysis(self, state: WorkflowState) -> bool:
        if "analyze_single_paper" not in state.metadata.get("planned_actions", []):
            return False
        if self._count_actions(state, "analyze_single_paper") >= ResearchBudget().max_paper_analyses:
            return False
        return self._should_analyze_single_paper_from_query(state.query, state.metadata.get("research_intent", ""))

    def _should_targeted_repair(self, state: WorkflowState, verification: Dict[str, Any]) -> bool:
        if state.metadata.get("targeted_repair_attempted"):
            return False
        if not state.evidence_items:
            return False
        if self._count_actions(state, "targeted_repair_search") >= 1:
            return False
        return verification.get("final_action") in {"revise", "refuse"} and bool(verification.get("unsupported_claims"))

    def _count_actions(self, state: WorkflowState, action: str) -> int:
        return sum(1 for item in state.metadata.get("research_actions", []) if item.get("action") == action and item.get("status") == "completed")

    def _record_action(self, state: WorkflowState, action: ResearchAction) -> None:
        if action.action not in ALLOWED_RESEARCH_ACTIONS:
            state.errors.append(f"不允许的研究 action: {action.action}")
            action.status = "failed"
        if action.node and action.next_node and action.next_node not in RESEARCH_TOOL_GRAPH.get(action.node, []):
            state.errors.append(f"非法工具拓扑: {action.node} -> {action.next_node}")
            action.status = "failed"
        state.metadata.setdefault("research_actions", []).append(action.to_dict())

    def _next_action_step(self, state: WorkflowState) -> int:
        return len(state.metadata.get("research_actions", [])) + 1

    def _tool_graph_metadata(self) -> Dict[str, Any]:
        return {
            "nodes": list(RESEARCH_TOOL_GRAPH.keys()),
            "edges": RESEARCH_TOOL_GRAPH,
            "tool_specs": {key: spec.to_dict() for key, spec in RESEARCH_TOOL_SPECS.items()},
            "intent_tools": RESEARCH_INTENT_TOOLS,
            "allowed_actions": sorted(ALLOWED_RESEARCH_ACTIONS),
        }

    def _retrieval_query_for_plan(self, plan: ExecutionPlan) -> str:
        for task in plan.tasks:
            if task.type in {"retrieve_papers", "retrieve_kg_context"} and task.query:
                return task.query
        return plan.goal

    def _retrieval_observation(self, retrieval: Dict[str, Any]) -> str:
        return "检索结果：bm25={bm25}, semantic={semantic}, graph={graph}, merged={merged}".format(
            bm25=len(retrieval.get("bm25_hits", []) or []),
            semantic=len(retrieval.get("semantic_hits", []) or []),
            graph=len(retrieval.get("graph_hits", []) or []),
            merged=len(retrieval.get("merged", []) or []),
        )

    def _evidence_observation(self, state: WorkflowState) -> str:
        if not state.evidence_items:
            return "没有可用证据"
        titles = [item.title for item in state.evidence_items[:3]]
        return f"累计 {len(state.evidence_items)} 条证据：" + "、".join(titles)

    def _external_search_reason(self, state: WorkflowState) -> str:
        if self._web_search_requested(state.query):
            return "用户显式要求联网或外部资料"
        if state.metadata.get("research_intent") == "literature_review":
            return "文献综述需要近年学术证据"
        if self._local_evidence_insufficient_for_web(state):
            return "本地证据不足，需要外部补证"
        return "本地证据不足，需要外部补证"

    def _contextual_query(self, query: str, context: AgentContext, decision=None) -> str:
        if not self._is_contextual_web_followup(query):
            return query
        if decision is not None and not getattr(decision, "context_dependent", False):
            return query
        memory_context = (context.extra or {}).get("memory_context", "") if context else ""
        recent_history = (context.extra or {}).get("recent_history", []) if context else []
        topic = self._topic_from_history(memory_context, recent_history)
        return f"{topic}\n{query}" if topic else query

    def _is_contextual_web_followup(self, query: str) -> bool:
        text = (query or "").strip()
        if not text or not self._web_search_requested(text):
            return False
        return len(text) <= 24 or any(term in text for term in ["继续", "补充", "查一下", "搜索一下"])

    def _topic_from_history(self, memory_context: str, recent_history: List[dict]) -> str:
        for msg in reversed(recent_history or []):
            if msg.get("role") != "user":
                continue
            content = (msg.get("content") or "").strip()
            if content and not self._is_contextual_web_followup(content):
                return content
        if memory_context:
            marker = "【最近原文】"
            recent = memory_context.split(marker, 1)[1] if marker in memory_context else memory_context
            for line in reversed(recent.splitlines()):
                line = line.strip()
                if not line.startswith("用户:"):
                    continue
                content = line.split("用户:", 1)[1].strip()
                if content and not self._is_contextual_web_followup(content):
                    return content
        return ""

    def _make_plan(self, query: str) -> ExecutionPlan:
        prompt = RESEARCH_PLANNER_PROMPT.format(query=query, allowed_tasks=", ".join(sorted(ALLOWED_RESEARCH_TASKS)))
        try:
            raw = self.llm.complete_json(prompt, {}) if self.llm else {}
        except Exception:
            raw = {}
        tasks_raw = raw.get("tasks") if isinstance(raw, dict) else None
        if not tasks_raw:
            tasks_raw = self._fallback_tasks(query)
        tasks = [
            PlannedTask(
                id=str(item.get("id") or f"t{index}"),
                type=str(item.get("type") or "summarize_evidence"),
                query=str(item.get("query") or query),
                target=str(item.get("target") or ""),
                depends_on=[str(dep) for dep in item.get("depends_on", [])],
                params=item.get("params", {}) if isinstance(item.get("params", {}), dict) else {},
            )
            for index, item in enumerate(tasks_raw, start=1)
        ]
        return ExecutionPlan(goal=str(raw.get("goal") or query) if isinstance(raw, dict) else query, tasks=tasks)

    def _fallback_tasks(self, query: str) -> List[Dict[str, Any]]:
        return [
            {"id": "t1", "type": "retrieve_papers", "query": query, "depends_on": [], "params": {}},
            {"id": "t2", "type": "summarize_evidence", "query": query, "depends_on": ["t1"], "params": {}},
            {"id": "t3", "type": "compare_methods", "query": query, "depends_on": ["t2"], "params": {}},
            {"id": "t4", "type": "find_research_gap", "query": query, "depends_on": ["t3"], "params": {}},
            {"id": "t5", "type": "generate_proposal", "query": query, "depends_on": ["t4"], "params": {}},
            {"id": "t6", "type": "verify_claims", "query": query, "depends_on": ["t5"], "params": {}},
        ]

    def _validate_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        if len(plan.tasks) > plan.budget.max_subtasks:
            verify_tasks = [task for task in plan.tasks if task.type == "verify_claims"]
            non_verify_tasks = [task for task in plan.tasks if task.type != "verify_claims"]
            plan.tasks = non_verify_tasks[: max(0, plan.budget.max_subtasks - 1)]
            plan.tasks.append(verify_tasks[0] if verify_tasks else PlannedTask(id=f"t{len(plan.tasks) + 1}", type="verify_claims", query=plan.goal))
        task_ids = {task.id for task in plan.tasks}
        for task in plan.tasks:
            task.depends_on = [dep for dep in task.depends_on if dep in task_ids]
            if task.type not in ALLOWED_RESEARCH_TASKS:
                raise ValueError(f"不允许的任务类型: {task.type}")
            unknown_deps = [dep for dep in task.depends_on if dep not in task_ids]
            if unknown_deps:
                raise ValueError(f"任务 {task.id} 依赖不存在: {unknown_deps}")
        if not any(task.type == "verify_claims" for task in plan.tasks):
            last_id = plan.tasks[-1].id if plan.tasks else "t0"
            plan.tasks.append(PlannedTask(id=f"t{len(plan.tasks) + 1}", type="verify_claims", query=plan.goal, depends_on=[last_id]))
        retrieval_calls = sum(1 for task in plan.tasks if task.type in {"retrieve_papers", "retrieve_kg_context"})
        if retrieval_calls > plan.budget.max_retrieval_calls:
            raise ValueError("检索调用超过预算")
        return plan

    def _retrieve_for_plan(self, plan: ExecutionPlan) -> Dict[str, Any]:
        retrieval_query = self._retrieval_query_for_plan(plan)
        return HybridSearchTool(self.db, self.llm).execute(retrieval_query, top_k=10)

    def _web_search_requested(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in ["联网", "搜索", "查找", "参考论文", "相关论文", "相关文献", "web search", "search"])

    def _search_web_evidence(self, query: str, missing_aspects: List[str], max_results: int = 6) -> List[Dict[str, Any]]:
        grade = EvidenceGradeData(
            relevance_score=0.0,
            support_score=0.0,
            coverage_score=0.0,
            freshness_required=self._research_needs_fresh_evidence(query),
            conflict_detected=False,
            sufficient=False,
            missing_aspects=missing_aspects[:5],
            next_action="web_verify",
            reason="研究工作流证据不足，触发联网补充",
        )
        search_mode = self._research_web_search_mode(query)
        return WebSearchVerifierAgent(self.db, self.llm).search_and_grade(query, grade, max_results=max_results, search_mode=search_mode)

    def _research_web_search_mode(self, query: str) -> str:
        lowered = (query or "").lower()
        has_paper_terms = any(term in lowered for term in [
            "论文", "文献", "paper", "papers", "survey", "related work", "研究现状", "研究背景", "相关工作", "研究空白", "引用", "参考文献", "开题",
        ])
        has_web_terms = any(term in lowered for term in [
            "官网", "官方", "政策", "公告", "报告", "github", "新闻", "行业资料", "行业", "公司", "产品", "文档",
            "official", "policy", "announcement", "report", "news", "industry",
        ])
        if has_paper_terms and has_web_terms:
            return "mixed"
        if has_paper_terms:
            return "academic"
        return "web"

    def _research_needs_fresh_evidence(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in [
            "最新", "当前", "近期", "现在", "趋势", "现状", "研究空白", "政策", "公告", "报告", "github", "benchmark", "paper", "论文", "2025", "2026", "近年",
        ])

    def _synthesize(self, query: str, plan: ExecutionPlan, state: WorkflowState) -> str:
        context_text = state.context_text() or "（没有足够证据）"
        memory_context = (state.context.extra or {}).get("memory_context", "") if state.context else ""
        web_evidence = state.metadata.get("retrieval", {}).get("web_evidence", [])
        web_context = self._format_web_evidence_for_synthesis(web_evidence)
        actions = json.dumps(state.metadata.get("research_actions", []), ensure_ascii=False)
        prompt = f"""你是研究分析助手。请基于证据回答用户的复杂研究问题。

【优先级规则】
1. 如果用户目标涉及"刚才、之前、继续、回到、这个选题、我们确定"等对话上下文，优先使用【对话记忆】回答。
2. 【外部证据】用于补充或验证，不得覆盖【对话记忆】中已经明确确定的用户方案、模块、技术路线或创新点。
3. 只有对话记忆缺失时，才说明缺少前文信息。

【用户目标】
{query}

【对话记忆】
{memory_context or '（无对话记忆）'}

【执行计划】
{json.dumps(plan.to_dict(), ensure_ascii=False)}

【研究动作轨迹】
{actions}

【本地证据】
{context_text}

【联网论文证据】
{web_context or '（无联网论文证据）'}

【回答要求】
1. 请输出结构化回答，包含结论、依据、对比/分析、下一步建议。
2. 不要编造证据；证据不足时必须明确说明。
3. 当【联网论文证据】中包含 [1]、[2] 等引用标记或 provider=ai4scholar 的论文证据时，必须在正文关键结论后标注对应引用，并在回答末尾增加"参考论文"小节，按编号列出标题、作者、年份、链接。

请直接返回答案。"""
        try:
            return self.llm.complete(prompt).content
        except Exception as exc:
            return f"[错误] 研究综合生成失败: {exc}"

    def _should_answer_from_memory(self, query: str, memory_context: str, decision=None) -> bool:
        if not memory_context:
            return False
        query = query or ""
        if self._web_search_requested(query):
            return False
        if decision is not None and getattr(decision, "context_dependent", False):
            return True
        return any(marker in query for marker in MEMORY_FIRST_MARKERS)

    def _answer_from_memory(self, query: str, memory_context: str) -> str:
        prompt = f"""你是研究助手。用户的问题是在追问之前对话中已经确定的研究方案。

【回答规则】
1. 只优先依据【对话记忆】回答，不要因为缺少外部检索证据而拒答。
2. 如果对话记忆中已经出现研究内容、技术路线、创新点、选题名称等信息，直接整理回答。
3. 如果某个细节在对话记忆中没有出现，明确说明"记忆中没有该细节"。
4. 回答要简洁、结构化。

【用户问题】
{query}

【对话记忆】
{memory_context}
"""
        try:
            return self.llm.complete(prompt).content
        except Exception as exc:
            return f"[错误] 记忆优先回答失败: {exc}"

    def _verify_claims(self, query: str, answer: str, retrieval: Dict[str, Any]) -> Dict[str, Any]:
        state = WorkflowState(query=query)
        state.add_evidence_from_retrieval(retrieval)
        verification = CitationVerifier(self.llm).verify(query, answer, state.evidence_items)
        return {
            "supported": verification.get("supported", False),
            "confidence": verification.get("support_score", 0.0),
            "reason": verification.get("reason", ""),
        }

    def _format_web_evidence_for_synthesis(self, web_evidence: List[Dict[str, Any]]) -> str:
        if not web_evidence:
            return ""
        lines = []
        for index, item in enumerate(web_evidence[:8], start=1):
            provider = item.get("provider", "unknown")
            title = item.get("title", "未命名")
            authors = item.get("authors", "")
            year = item.get("year", "")
            snippet = item.get("snippet", "")[:300]
            url = item.get("url", "")
            paper_id = item.get("paper_id", "")
            citation = item.get("citation", f"[{index}]")

            meta_parts = []
            if authors:
                meta_parts.append(str(authors)[:80])
            if year:
                meta_parts.append(str(year))
            if provider == "ai4scholar":
                meta_parts.append("provider=ai4scholar")
            if paper_id:
                meta_parts.append(f"paper_id={paper_id}")
            meta = " | ".join(meta_parts) if meta_parts else ""

            line = f"- {citation} {title}"
            if meta:
                line += f" [{meta}]"
            line += f": {snippet}"
            if url:
                line += f" ({url})"
            lines.append(line)
        return "\n".join(lines)

    def _format_sources(self, items: list, web_evidence: Optional[List[Dict[str, Any]]] = None) -> list:
        sources = []
        seen = set()
        for item in items:
            key = f"{item.get('result_type')}:{item.get('chunk_id') or item.get('node_id') or item.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "id": item.get("chunk_id") or item.get("node_id") or item.get("id") or 0,
                "name": item.get("paper_title") or item.get("title") or item.get("name") or "研究证据",
                "type": item.get("result_type", "document"),
                "description": (item.get("content") or item.get("description") or "")[:160],
                "chunk_type": item.get("chunk_type") or item.get("section_type"),
                "source": item.get("source"),
            })
        if web_evidence:
            for index, item in enumerate(web_evidence[:6], start=1):
                key = item.get("paper_id") or item.get("url") or item.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                citation = item.get("citation", f"[{index}]")
                sources.append({
                    "id": item.get("paper_id") or item.get("url") or index,
                    "name": item.get("title") or "外部论文",
                    "type": item.get("result_type", "web_evidence"),
                    "description": (item.get("snippet") or "")[:160],
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "authors": item.get("authors"),
                    "year": item.get("year"),
                    "paper_id": item.get("paper_id"),
                    "provider": item.get("provider"),
                    "citation": citation,
                })
        return sources
