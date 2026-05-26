"""
论文参考助手 Agent：按论文任务模式检索并生成回答。
"""

from typing import Any, Dict, List
import time
from sqlalchemy.orm import Session

from agents.evidence_grader import EvidenceGraderAgent
from agents.paper_experts import PaperExpertInput, create_paper_expert
from agents.paper_task_router import PaperTaskPlan, PaperTaskRouter
from agents.retrieval_repair import RetrievalRepairAgent
from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from models.db import Document, DocumentChunk
from models.schemas import EvidenceGradeData
from tools.hybrid_search import HybridSearchTool
from observability.langsmith_tracing import traceable


PAPER_ASSISTANT_PROMPT = """你是论文参考助手，面向本科生和研究生，必须基于给定证据回答。

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
3. 根据任务类型组织答案：
   - paper_overview：按研究问题、核心方法、主要贡献、结论/局限组织。
   - method_explanation：按方法动机、关键模块、流程、与相关方法差异组织。
   - experiment_analysis：按数据集、指标、实验结论、可疑不足组织。
   - method_comparison：用分点或表格比较目标、机制、证据和适用场景。
   - literature_review：按主题归纳研究脉络，不要伪造不存在的引用。
   - writing_outline：给出可写成论文/开题报告的章节大纲，并标注每节依赖的证据类型。
4. 尽量引用章节来源，例如 [abstract Introduction]、[method Method]、[experiment Results]。
5. 输出中文，结构清晰。

请直接返回答案。
"""


class PaperAssistantAgent(BaseAgent):
    """论文参考助手 Manager Agent。"""

    def __init__(self, db: Session, llm=None):
        super().__init__(
            name="PaperAssistant",
            role="paper_assistant",
            description="根据论文参考任务路由检索并生成结构化回答",
        )
        from llm.manager import llm_manager
        self.db = db
        self.llm = llm if llm is not None else llm_manager
        self.router = PaperTaskRouter()
        self.search_tool = HybridSearchTool(db, self.llm)
        self.grader = EvidenceGraderAgent(self.llm)
        self.repairer = RetrievalRepairAgent(self.llm)

    @traceable(name="paper_assistant.execute", run_type="chain")
    def execute(self, context: AgentContext) -> AgentResult:
        query = context.pipeline_data.query
        if not query:
            return AgentResult(success=False, message="查询为空")

        memory_context = context.extra.get("memory_context", "") if context.extra else ""
        if memory_context:
            query = f"{query}\n\n{memory_context}"

        plan_start = time.perf_counter()
        plan = self.router.route(query)
        performance = {"routing": round(time.perf_counter() - plan_start, 3)}

        retrieval_override = self._build_retrieval_override(plan)
        retrieval_start = time.perf_counter()
        retrieval = self.search_tool.execute(query, top_k=8, plan_override=retrieval_override)
        performance["retrieval"] = round(time.perf_counter() - retrieval_start, 3)

        grade_start = time.perf_counter()
        grade = self._grade_paper_evidence(query, retrieval, plan, round_index=1)
        performance["grading"] = round(time.perf_counter() - grade_start, 3)
        performance["repair"] = 0.0
        retrieval_rounds = [{
            "round": 1,
            "query": query,
            "source": "local",
            "grade": grade.__dict__,
            "retrieval": self._retrieval_stats(retrieval),
        }]

        if not grade.sufficient and grade.next_action in {"rewrite_local", "adjust_strategy"}:
            repair_start = time.perf_counter()
            repair = self.repairer.repair(query, retrieval, grade)
            repaired_override = dict(retrieval_override)
            repaired_override.update(repair.get("strategy", {}))
            repaired_override["optimized_query"] = repair.get("rewritten_query") or query
            repaired_override["expanded_queries"] = repair.get("expanded_queries", [])
            repaired_override["preferred_chunk_types"] = plan.preferred_chunk_types
            if repair.get("rewritten_query"):
                repaired_override["strict_bm25_terms"] = True
            repaired_query = repair.get("rewritten_query") or query
            repaired = self.search_tool.execute(repaired_query, top_k=8, plan_override=repaired_override)
            repaired_grade = self._grade_paper_evidence(repaired_query, repaired, plan, round_index=2)
            performance["repair"] = round(time.perf_counter() - repair_start, 3)
            retrieval_rounds.append({
                "round": 2,
                "query": repaired_query,
                "source": "local_repair",
                "repair": repair,
                "grade": repaired_grade.__dict__,
                "retrieval": self._retrieval_stats(repaired),
            })
            if repaired_grade.coverage_score >= grade.coverage_score or repaired_grade.sufficient:
                retrieval = repaired
                grade = repaired_grade

        context_start = time.perf_counter()
        context_text = self._filter_context_text(retrieval, plan)
        performance["context"] = round(time.perf_counter() - context_start, 3)

        try:
            generation_start = time.perf_counter()
            expert_input = PaperExpertInput(
                query=query,
                plan=plan,
                context_text=context_text or "（暂无足够论文证据）",
                preferred_types=", ".join(plan.preferred_chunk_types),
            )
            expert_context = AgentContext(
                pipeline_data=context.pipeline_data,
                extra={"paper_expert_input": expert_input},
            )
            expert = create_paper_expert(plan.task_type, self.llm)
            expert_result = expert.run(expert_context)
            if not expert_result.success or not expert_result.output:
                return AgentResult(success=False, message=expert_result.message, errors=expert_result.errors)
            answer = expert_result.output.get("answer", "")
            expert_role = expert_result.output.get("expert", expert.role)
            performance["generation"] = round(time.perf_counter() - generation_start, 3)
        except Exception as exc:
            return AgentResult(success=False, message=f"论文参考回答生成失败: {exc}", errors=[str(exc)])

        sources_start = time.perf_counter()
        sources = self._format_sources(retrieval.get("merged", []), plan)
        if not sources:
            sources = self._fallback_sources(plan)
        performance["sources"] = round(time.perf_counter() - sources_start, 3)
        performance["total"] = round(sum(performance.values()), 3)
        return AgentResult(
            success=True,
            output={
                "answer": answer,
                "sources": sources,
                "paper_task": {**plan.to_dict(), "expert": expert_role},
                "retrieval_plan": retrieval.get("plan", {}),
                "context_text": context_text,
                "evidence_grade": grade.__dict__,
                "retrieval_rounds": retrieval_rounds,
                "performance": performance,
                "confidence": max(0.45, grade.coverage_score),
            },
            message=f"论文参考助手完成：{plan.task_type}",
            confidence=max(0.45, grade.coverage_score),
        )

    def _build_retrieval_override(self, plan: PaperTaskPlan) -> Dict[str, Any]:
        override = dict(plan.retrieval_override)
        override["preferred_chunk_types"] = plan.preferred_chunk_types
        override.setdefault("bm25_top_k", 8)
        override.setdefault("vector_top_k", 8)
        override.setdefault("graph_top_k", 6)
        if plan.task_type in {"overview", "method", "experiment", "outline"}:
            override.setdefault("graph", False)
            override.setdefault("graph_method", "none")
        return override

    def _grade_paper_evidence(self, query: str, retrieval: Dict[str, Any], plan: PaperTaskPlan, round_index: int = 1):
        required = self._required_chunk_types(plan.task_type)
        available = self._available_chunk_types(retrieval)
        missing = [item for item in required if item not in available]
        if not missing and (available or retrieval.get("merged")) and not self._freshness_required(query):
            return EvidenceGradeData(
                relevance_score=0.82,
                support_score=0.78,
                coverage_score=0.78,
                freshness_required=False,
                conflict_detected=False,
                sufficient=True,
                missing_aspects=[],
                next_action="answer",
                reason="论文任务必要证据类型已覆盖，跳过额外证据评估",
            )
        grade = self.grader.grade(query, retrieval, round_index=round_index)
        if missing:
            grade.sufficient = False
            grade.missing_aspects = list(dict.fromkeys(grade.missing_aspects + [f"缺少论文证据类型: {', '.join(missing)}"]))
            grade.coverage_score = min(grade.coverage_score, 0.62)
            grade.support_score = min(grade.support_score, 0.66)
            grade.next_action = "web_verify" if round_index >= 2 and grade.freshness_required else "adjust_strategy"
            grade.reason = f"论文任务证据不完整，缺少 {', '.join(missing)}"
        elif available or retrieval.get("merged"):
            grade.relevance_score = max(grade.relevance_score, 0.75)
            grade.support_score = max(grade.support_score, 0.72)
            grade.coverage_score = max(grade.coverage_score, 0.72)
            if not grade.freshness_required:
                grade.sufficient = True
                grade.next_action = "answer"
                grade.reason = grade.reason or "论文任务必要证据类型已覆盖"
        return grade

    def _freshness_required(self, query: str) -> bool:
        terms = ["最新", "当前", "近期", "现在", "2026", "version", "release", "changelog", "benchmark"]
        lowered = (query or "").lower()
        return any(term.lower() in lowered for term in terms)

    def _required_chunk_types(self, task_type: str) -> List[str]:
        requirements = {
            "overview": ["abstract"],
            "method": ["method"],
            "experiment": ["experiment"],
            "compare": ["method", "experiment"],
            "literature_review": ["related_work", "reference"],
            "outline": ["abstract", "method", "experiment"],
        }
        return requirements.get(task_type, [])

    def _available_chunk_types(self, retrieval: Dict[str, Any]) -> set:
        types = set()
        query_terms = {
            term.lower()
            for term in (retrieval.get("optimized_query") or "").split()
            if len(term) >= 4
            and term.lower() not in {"experiment", "dataset", "metric", "table", "paper", "method"}
            and any(ch.isdigit() for ch in term)
        }
        ranked_hits = retrieval.get("merged", [])[:8]
        if not ranked_hits:
            ranked_hits = (retrieval.get("bm25_hits", []) + retrieval.get("semantic_hits", []))[:8]
        for hit in ranked_hits:
            content = f"{hit.get('title') or ''}\n{hit.get('content') or hit.get('description') or ''}".lower()
            if query_terms and not any(term in content for term in query_terms):
                if hit.get("result_type") == "chunk" and (hit.get("chunk_type") or hit.get("section_type")):
                    continue
            chunk_type = hit.get("chunk_type") or hit.get("section_type")
            if chunk_type:
                types.add(chunk_type)
        return types

    def _retrieval_stats(self, retrieval: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "bm25_hits": len(retrieval.get("bm25_hits", [])),
            "semantic_hits": len(retrieval.get("semantic_hits", [])),
            "graph_hits": len(retrieval.get("graph_hits", [])),
            "merged": len(retrieval.get("merged", [])),
            "chunk_types": sorted(self._available_chunk_types(retrieval)),
        }

    def _filter_context_text(self, retrieval: Dict[str, Any], plan: PaperTaskPlan) -> str:
        preferred = set(plan.preferred_chunk_types)
        doc_hits = []
        other_hits = []
        seen = set()
        for hit in retrieval.get("merged", []):
            if hit.get("result_type") != "chunk":
                continue
            key = hit.get("chunk_id") or hit.get("id")
            if key in seen:
                continue
            seen.add(key)
            if hit.get("chunk_type") in preferred or hit.get("section_type") in preferred:
                doc_hits.append(hit)
            else:
                other_hits.append(hit)
        limit_by_task = {
            "overview": 6,
            "method": 6,
            "experiment": 6,
            "compare": 8,
            "literature_review": 8,
            "outline": 6,
        }
        selected = (doc_hits + other_hits)[:limit_by_task.get(plan.task_type, 6)]
        if not selected:
            return retrieval.get("context_text", "")

        lines = [
            f"【用户问题】{retrieval.get('optimized_query') or ''}",
            f"【论文任务】{plan.task_type} - {plan.reason}",
            "【论文证据】",
        ]
        for hit in selected:
            title = hit.get("paper_title") or hit.get("title") or "未命名论文"
            chunk_type = hit.get("chunk_type") or hit.get("section_type") or "chunk"
            section = hit.get("section_path") or ""
            content = (hit.get("content") or "")[:520]
            lines.append(f"- {title} [{chunk_type} {section}]: {content}")
        graph_hits = retrieval.get("graph_hits", [])[:4]
        if graph_hits:
            lines.append("【关系证据】")
            for hit in graph_hits:
                lines.append(f"- {hit.get('description') or hit.get('name') or hit}")
        return "\n".join(lines)

    def _format_sources(self, hits: List[Dict[str, Any]], plan: PaperTaskPlan) -> List[Dict[str, Any]]:
        sources = []
        seen = set()
        preferred = set(plan.preferred_chunk_types)
        ordered = sorted(
            hits,
            key=lambda h: 0 if (h.get("chunk_type") in preferred or h.get("section_type") in preferred) else 1,
        )
        for hit in ordered:
            key = f"{hit.get('result_type')}:{hit.get('chunk_id') or hit.get('node_id') or hit.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "id": hit.get("chunk_id") or hit.get("node_id") or hit.get("id"),
                "name": hit.get("paper_title") or hit.get("title") or hit.get("name") or "未知来源",
                "type": hit.get("result_type", "chunk"),
                "chunk_type": hit.get("chunk_type") or hit.get("section_type"),
                "section_path": hit.get("section_path"),
                "source": hit.get("source"),
            })
            if len(sources) >= 8:
                break
        return sources

    def _fallback_sources(self, plan: PaperTaskPlan) -> List[Dict[str, Any]]:
        preferred = set(plan.preferred_chunk_types)
        chunks = (
            self.db.query(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .order_by(DocumentChunk.created_at.desc())
            .limit(80)
            .all()
        )
        sources = []
        for chunk, doc in chunks:
            metadata = self.search_tool._extract_chunk_metadata(chunk.content)
            chunk_type = metadata.get("chunk_type")
            if preferred and chunk_type not in preferred:
                continue
            sources.append({
                "id": chunk.id,
                "name": metadata.get("paper_title") or doc.title,
                "type": "chunk",
                "chunk_type": chunk_type,
                "section_path": metadata.get("section_path"),
                "source": doc.source,
            })
            if len(sources) >= 5:
                break
        return sources
