from dataclasses import asdict, dataclass, field
import json
import time
from typing import Any, Dict, List

from agents.citation_verifier import CitationVerifier
from agents.web_verifier import WebSearchVerifierAgent
from core.agent import AgentResult
from core.context import AgentContext
from core.graph_state import ClaimItem, WorkflowState
from core.orchestrator import BaseWorkflow, WorkflowResult
from core.state_graph import GraphEdge, GraphNode, StateGraphRunner
from models.schemas import EvidenceGradeData
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

MEMORY_FIRST_MARKERS = [
    "刚才", "之前", "前文", "上面", "继续", "回到", "我们确定", "已确定",
    "这个选题", "该选题", "这个方案", "这个研究", "不看前文", "刚刚",
]


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
        memory_context = (context.extra or {}).get("memory_context", "")
        query = self._contextual_query(context.pipeline_data.query, context, decision)
        if self._should_answer_from_memory(query, memory_context, decision):
            answer = self._answer_from_memory(query, memory_context)
            elapsed = time.time() - start
            return WorkflowResult(
                success=not answer.startswith("[错误]"),
                path="research",
                response=answer,
                confidence=0.82 if not answer.startswith("[错误]") else 0.0,
                processing_time=f"{elapsed:.1f}s",
                metadata={"memory_first": True},
            )

        graph_state = WorkflowState(
            query=query,
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
        if self._should_supplement_web(state, verification):
            web_items = self._supplement_with_web(state, verification)
            if web_items:
                verification = CitationVerifier(self.llm).verify(state.query, state.answer_draft, state.evidence_items)
                state.metadata["auto_web_supplemented"] = True
                state.metadata["web_evidence_count"] = len(web_items)
            else:
                state.metadata["auto_web_supplemented"] = False
                state.metadata["web_evidence_count"] = 0
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
        retrieval = HybridSearchTool(self.db, self.llm).execute(retrieval_query, top_k=10)
        if self._web_search_requested(plan.goal):
            web_items = self._search_web_evidence(retrieval_query, ["用户显式要求联网或外部资料"], max_results=6)
            if web_items:
                # 添加citation标记
                for index, item in enumerate(web_items, start=1):
                    item["citation"] = f"[{index}]"
                retrieval.setdefault("merged", [])
                retrieval["merged"] = web_items + retrieval["merged"]
                retrieval["web_evidence"] = web_items
                retrieval["web_search_provider"] = "mixed"
        return retrieval

    def _web_search_requested(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in ["联网", "搜索", "查找", "参考论文", "相关论文", "相关文献", "web search", "search"])

    def _should_supplement_web(self, state: WorkflowState, verification: Dict[str, Any]) -> bool:
        if state.metadata.get("auto_web_supplement_attempted"):
            return False
        if self._should_answer_from_memory(state.query, (state.context.extra or {}).get("memory_context", "") if state.context else ""):
            return False
        support_score = float(verification.get("support_score", 0.0) or 0.0)
        unsupported = verification.get("unsupported_claims") or []
        return (
            verification.get("final_action") in {"revise", "refuse"}
            or not verification.get("supported", False)
            or support_score < 0.65
            or bool(unsupported)
            or self._research_needs_fresh_evidence(state.query)
        )

    def _supplement_with_web(self, state: WorkflowState, verification: Dict[str, Any]) -> List[Dict[str, Any]]:
        state.metadata["auto_web_supplement_attempted"] = True
        missing = verification.get("unsupported_claims") or ["本地研究证据不足"]
        web_items = self._search_web_evidence(state.query, missing, max_results=6)
        if not web_items:
            return []
        # 添加citation标记
        for index, item in enumerate(web_items, start=1):
            item["citation"] = f"[{index}]"
        retrieval = state.metadata.get("retrieval") or {}
        retrieval.setdefault("merged", [])
        retrieval["merged"] = web_items + retrieval["merged"]
        retrieval["web_evidence"] = web_items
        retrieval["web_search_provider"] = "mixed"
        state.metadata["retrieval"] = retrieval
        state.add_evidence_from_retrieval({"web_evidence": web_items})
        return web_items

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
            "最新", "当前", "近期", "现在", "趋势", "现状", "研究空白", "依据", "证据", "验证",
            "可靠吗", "可靠性", "政策", "公告", "报告", "github", "benchmark", "paper", "论文",
        ])

    def _synthesize(self, query: str, plan: ExecutionPlan, state: WorkflowState) -> str:
        context_text = state.context_text() or "（没有足够证据）"
        memory_context = (state.context.extra or {}).get("memory_context", "") if state.context else ""
        web_evidence = state.metadata.get("retrieval", {}).get("web_evidence", [])
        web_context = self._format_web_evidence_for_synthesis(web_evidence)
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

【本地证据】
{context_text}

【联网论文证据】
{web_context or '（无联网论文证据）'}

【回答要求】
1. 请输出结构化回答，包含结论、依据、对比/分析、下一步建议。
2. 不要编造证据。
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
                meta_parts.append(f"provider=ai4scholar")
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

    def _format_sources(self, items: list, web_evidence: List[Dict[str, Any]] | None = None) -> list:
        sources = []
        seen = set()
        # 本地证据
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
        # 联网论文证据
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
