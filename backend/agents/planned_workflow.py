from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Dict, List

from agents.citation_verifier import CitationVerifier
from core.agent import AgentResult
from core.context import AgentContext
from core.graph_state import ClaimItem, WorkflowState
from core.orchestrator import BaseWorkflow, WorkflowResult
from core.state_graph import GraphEdge, GraphNode, StateGraphRunner
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


@dataclass
class PlanningBudget:
    max_subtasks: int = 8
    max_retrieval_calls: int = 5
    max_llm_calls: int = 8
    max_web_calls: int = 1
    max_runtime_seconds: int = 60


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

    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        graph_state = WorkflowState(
            query=context.pipeline_data.query,
            route_decision=decision.to_dict() if decision else None,
            context=context,
        )
        graph_state.metadata["started_at"] = start
        graph = StateGraphRunner(
            nodes=[
                GraphNode("planner", self._planner_node),
                GraphNode("retrieval", self._retrieval_node),
                GraphNode("synthesis", self._synthesis_node),
                GraphNode("citation_verifier", self._citation_verifier_node),
                GraphNode("finalize", self._finalize_node),
            ],
            edges=[
                GraphEdge("planner", "retrieval", lambda state: not state.errors),
                GraphEdge("retrieval", "synthesis", lambda state: not state.errors),
                GraphEdge("synthesis", "citation_verifier", lambda state: not state.errors),
                GraphEdge("citation_verifier", "finalize"),
            ],
            start_node="planner",
        )
        graph_state = graph.run(graph_state)
        elapsed = time.time() - start
        confidence = graph_state.verification.get("support_score", graph_state.verification.get("confidence", 0.5))
        result = graph_state.to_workflow_result("research", confidence=confidence, processing_time=f"{elapsed:.1f}s")
        if graph_state.errors and not result.response:
            result.response = f"[错误] 研究工作流执行失败: {'; '.join(graph_state.errors)}"
        return result

    async def run_async(self, context: AgentContext, decision=None):
        yield {"type": "status", "agent": "ResearchPlanner", "step": "规划研究子任务", "elapsed": 0.0}
        result = self.run(context, decision)
        yield {"type": "status", "agent": "ResearchWorkflow", "step": "综合研究结果", "elapsed": 0.0}
        if result.sources:
            yield {"type": "sources", "data": result.sources}
        for char in result.response:
            yield {"type": "delta", "content": char}
        yield {"type": "metrics", "path": "research", "processing_time": result.processing_time, "confidence": result.confidence, **result.metadata}

    def _planner_node(self, state: WorkflowState) -> WorkflowState:
        plan = self._validate_plan(self._make_plan(state.query))
        state.metadata["research_plan"] = plan.to_dict()
        state.metadata["plan"] = plan
        state.next_action = "retrieve"
        return state

    def _retrieval_node(self, state: WorkflowState) -> WorkflowState:
        plan = state.metadata["plan"]
        retrieval = self._retrieve_for_plan(plan)
        state.metadata["retrieval"] = retrieval
        state.add_evidence_from_retrieval(retrieval)
        state.next_action = "synthesize"
        return state

    def _synthesis_node(self, state: WorkflowState) -> WorkflowState:
        plan = state.metadata["plan"]
        state.answer_draft = self._synthesize(state.query, plan, state)
        state.next_action = "verify_citations"
        return state

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
        state.next_action = "finalize"
        return state

    def _finalize_node(self, state: WorkflowState) -> WorkflowState:
        state.metadata.pop("plan", None)
        state.metadata.pop("retrieval", None)
        state.next_action = "done"
        return state

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
            raise ValueError("子任务数量超过预算")
        task_ids = {task.id for task in plan.tasks}
        for task in plan.tasks:
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
        retrieval_query = plan.goal
        for task in plan.tasks:
            if task.type in {"retrieve_papers", "retrieve_kg_context"} and task.query:
                retrieval_query = task.query
                break
        return HybridSearchTool(self.db, self.llm).execute(retrieval_query, top_k=10)

    def _synthesize(self, query: str, plan: ExecutionPlan, state: WorkflowState) -> str:
        context_text = state.context_text() or "（暂无足够证据）"
        prompt = f"""你是研究分析助手。请基于证据完成用户的复杂研究任务。

【用户目标】
{query}

【执行计划】
{json.dumps(plan.to_dict(), ensure_ascii=False)}

【证据】
{context_text}

请输出中文，包含：结论、依据、对比/分析、下一步建议。不要编造证据。"""
        try:
            return self.llm.complete(prompt).content
        except Exception as exc:
            return f"[错误] 研究综合生成失败: {exc}"

    def _verify_claims(self, query: str, answer: str, retrieval: Dict[str, Any]) -> Dict[str, Any]:
        state = WorkflowState(query=query)
        state.add_evidence_from_retrieval(retrieval)
        verification = CitationVerifier(self.llm).verify(query, answer, state.evidence_items)
        return {
            "supported": verification.get("supported", False),
            "confidence": verification.get("support_score", 0.0),
            "reason": verification.get("reason", ""),
        }

    def _format_sources(self, items: list) -> list:
        sources = []
        for item in items:
            sources.append({
                "id": item.get("chunk_id") or item.get("node_id") or item.get("id") or 0,
                "name": item.get("paper_title") or item.get("title") or item.get("name") or "研究证据",
                "type": item.get("result_type", "document"),
                "description": (item.get("content") or item.get("description") or "")[:160],
                "chunk_type": item.get("chunk_type") or item.get("section_type"),
                "source": item.get("source"),
            })
        return sources
