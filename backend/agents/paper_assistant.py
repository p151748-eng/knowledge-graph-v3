"""
论文参考助手 Agent：按论文任务模式检索并生成回答。
"""

from typing import Any, Dict, List
import re
import time
from sqlalchemy.orm import Session

from agents.evidence_grader import EvidenceGraderAgent
from agents.paper_experts import PaperExpertInput, create_paper_expert
from agents.paper_task_router import PaperTaskPlan, PaperTaskRouter
from agents.retrieval_repair import RetrievalRepairAgent
from agents.web_verifier import WebSearchVerifierAgent
from core.agent import BaseAgent, AgentResult
from core.context import AgentContext
from models.db import Document, DocumentChunk
from models.schemas import EvidenceGradeData
from tools.academic_search import AcademicSearchTool
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
        self.web_verifier = WebSearchVerifierAgent(db, self.llm)
        self.academic_search = AcademicSearchTool(db, llm=self.llm)

    @traceable(name="paper_assistant.execute", run_type="chain")
    def execute(self, context: AgentContext) -> AgentResult:
        user_query = context.pipeline_data.query
        if not user_query:
            return AgentResult(success=False, message="查询为空")

        memory_context = context.extra.get("memory_context", "") if context.extra else ""
        recent_history = context.extra.get("recent_history", []) if context.extra else []
        route_metadata = (context.extra or {}).get("route_decision", {}).get("metadata", {}) if context.extra else {}
        web_search_requested = bool(route_metadata.get("web_search_requested")) or self._web_search_requested(user_query)
        query = f"{user_query}\n\n{memory_context}" if memory_context else user_query

        plan_start = time.perf_counter()
        plan = self.router.route(query)
        performance = {"routing": round(time.perf_counter() - plan_start, 3)}

        retrieval_override = self._build_retrieval_override(plan)
        retrieval_start = time.perf_counter()
        retrieval = self.search_tool.execute(query, top_k=8, plan_override=retrieval_override)
        performance["retrieval"] = round(time.perf_counter() - retrieval_start, 3)

        web_evidence: List[Dict[str, Any]] = []
        performance["web"] = 0.0
        if web_search_requested:
            web_start = time.perf_counter()
            enrichment_query = self._web_enrichment_query(user_query, memory_context, plan, recent_history)
            web_evidence = self._external_evidence(enrichment_query, user_query, plan, memory_context)
            performance["web"] = round(time.perf_counter() - web_start, 3)

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
                query=user_query,
                plan=plan,
                context_text=context_text or "（暂无足够论文证据）",
                preferred_types=", ".join(plan.preferred_chunk_types),
                memory_context=memory_context,
                web_context=self._format_web_context(web_evidence),
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
            if web_evidence:
                answer = self._ensure_reference_links(answer, web_evidence)
            if not web_search_requested and self._should_prompt_web_supplement(user_query, grade, context_text):
                answer = self._append_web_supplement_prompt(answer, grade)
            expert_role = expert_result.output.get("expert", expert.role)
            performance["generation"] = round(time.perf_counter() - generation_start, 3)
        except Exception as exc:
            return AgentResult(success=False, message=f"论文参考回答生成失败: {exc}", errors=[str(exc)])

        sources_start = time.perf_counter()
        sources = self._format_sources(retrieval.get("merged", []), plan)
        sources = self._merge_sources(sources, self._format_external_sources(web_evidence))
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
                "web_evidence": web_evidence,
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

    def _external_evidence(self, enrichment_query: str, user_query: str, plan: PaperTaskPlan, memory_context: str) -> List[Dict[str, Any]]:
        if self._needs_academic_search(user_query, plan, memory_context):
            academic_items = self._academic_evidence(enrichment_query, max_results=8)
            if len(academic_items) < 3:
                rewritten_query = self._rewrite_academic_query_with_llm(enrichment_query, user_query, memory_context)
                if rewritten_query and rewritten_query != enrichment_query:
                    academic_items = self._merge_external_evidence(academic_items, self._academic_evidence(rewritten_query, max_results=8), limit=8)
            if academic_items and not self._needs_web_search(user_query):
                return academic_items
            web_items = self.web_verifier.search_and_grade(enrichment_query, max_results=5, search_mode="web") if self._needs_web_search(user_query) or not academic_items else []
            return self._merge_external_evidence(academic_items, web_items, limit=8)
        search_mode = "mixed" if self._needs_web_search(user_query) and self.web_verifier._needs_academic_search(enrichment_query) else "web"
        return self.web_verifier.search_and_grade(enrichment_query, max_results=5, search_mode=search_mode)

    def _academic_evidence(self, query: str, max_results: int = 8) -> List[Dict[str, Any]]:
        raw = self.academic_search.execute(query, max_results=max(max_results * 2, 12))
        strict_items = self._filter_academic_items(raw.get("results", []), query, max_results=max_results, strict=True)
        if len(strict_items) >= min(3, max_results):
            return strict_items[:max_results]
        relaxed_items = self._filter_academic_items(raw.get("results", []), query, max_results=max_results, strict=False)
        return self._merge_external_evidence(strict_items, relaxed_items, limit=max_results)

    def _filter_academic_items(self, results: List[Dict[str, Any]], query: str, max_results: int, strict: bool) -> List[Dict[str, Any]]:
        scored = []
        for index, item in enumerate(results):
            if not self._is_usable_academic_evidence(item):
                continue
            score = self._academic_relevance_score(item, query)
            threshold = 0.18 if strict else 0.08
            if score < threshold:
                continue
            enriched = dict(item)
            enriched.setdefault("id", index)
            enriched.setdefault("index", index)
            enriched.setdefault("result_type", "web_evidence")
            enriched.setdefault("type", "web")
            enriched.setdefault("provider", "ai4scholar")
            enriched["description"] = self._citation_description(enriched)
            enriched["relevance_score"] = round(score, 3)
            scored.append(enriched)
        scored.sort(key=lambda item: (-float(item.get("relevance_score", 0)), -float(item.get("quality_score", 0) or 0), -(int(str(item.get("year") or 0)[:4]) if str(item.get("year") or "").isdigit() else 0)))
        for idx, item in enumerate(scored[:max_results], start=1):
            item["citation"] = self._citation_label(item, idx)
        return scored[:max_results]

    def _rewrite_academic_query_with_llm(self, enrichment_query: str, user_query: str, memory_context: str) -> str:
        try:
            prompt = f"""你是学术搜索 query 重写器。请只输出 JSON，不要回答用户问题。

【当前用户请求】
{user_query}

【对话主题/上下文】
{memory_context or '（无）'}

【当前规则 query】
{enrichment_query}

目标：如果当前请求是“这个选题/该方向/上述主题”的上下文追问，请从上下文还原真实 topic，并拆出年份约束。输出适合 AI4Scholar / Semantic Scholar 的英文关键词 query，避免把“这个选题、相关论文、重点找、以后”等中文指令词当关键词。

返回格式：
{{
  "topic": "multi-agent RAG in medical paper reading",
  "intent": "find_recent_papers",
  "year_range": "2024-2026",
  "queries": [
    "\"multi-agent RAG\" biomedical literature",
    "\"agentic RAG\" medical literature review",
    "\"retrieval augmented generation\" biomedical literature multi-agent"
  ]
}}
"""
            data = self.llm.complete_json(prompt, {})
            queries = [str(item).strip() for item in data.get("queries", []) if str(item).strip()]
            year_range = str(data.get("year_range") or "").strip()
            if year_range and not any(year_range in query for query in queries):
                queries = [f"{query} {year_range.split('-', 1)[0]}" for query in queries]
            return " || ".join(queries[:6])
        except Exception:
            return ""

    def _is_usable_academic_evidence(self, item: Dict[str, Any]) -> bool:
        if not item.get("title") or item.get("title") == "搜索失败":
            return False
        return any(item.get(field) for field in ["authors", "year", "snippet", "url", "paper_id"])

    def _academic_relevance_score(self, item: Dict[str, Any], query: str) -> float:
        query_tokens = self._academic_relevance_tokens(query)
        evidence_text = f"{item.get('title') or ''}\n{item.get('snippet') or ''}".lower()
        if not evidence_text.strip():
            return 0.0
        if self._is_recent_required(query):
            try:
                year = int(str(item.get("year") or "0")[:4])
            except ValueError:
                year = 0
            if year and year < 2024:
                return 0.0
        if not query_tokens:
            return 0.3
        matched_weight = 0.0
        total_weight = sum(weight for _, weight in query_tokens)
        for token, weight in query_tokens:
            if token in evidence_text:
                matched_weight += weight
        phrase_bonus = 0.0
        for phrase in re.findall(r'"([^"]+)"', query or ""):
            normalized = phrase.lower().strip()
            if normalized and normalized in evidence_text:
                phrase_bonus += 0.12
        return min(1.0, matched_weight / max(total_weight, 1.0) + phrase_bonus)

    def _academic_relevance_tokens(self, query: str) -> List[tuple[str, float]]:
        text = (query or "").lower()
        stopwords = {
            "paper", "papers", "literature", "review", "study", "studies", "research", "related", "latest", "recent",
            "after", "since", "using", "based", "application", "applications", "analysis", "method", "methods",
            "论文", "文献", "研究", "相关", "最新", "这个", "选题", "方向", "应用", "分析", "方法", "以后", "以来",
        }
        raw_tokens = re.findall(r"[a-z][a-z0-9-]{2,}|[一-龥]{2,8}", text)
        tokens = []
        seen = set()
        for token in raw_tokens:
            if token in stopwords or re.fullmatch(r"20\d{2}", token):
                continue
            if token in seen:
                continue
            seen.add(token)
            weight = 1.0
            if len(token) >= 8 or "-" in token:
                weight = 1.4
            if re.search(r"[一-龥]", token):
                weight = 1.2
            tokens.append((token, weight))
            if len(tokens) >= 14:
                break
        return tokens

    def _is_relevant_academic_evidence(self, item: Dict[str, Any], query: str, strict: bool = True) -> bool:
        threshold = 0.18 if strict else 0.08
        return self._academic_relevance_score(item, query) >= threshold

    def _merge_external_evidence(self, primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        merged = []
        seen = set()
        for item in primary + secondary:
            key = (item.get("paper_id") or item.get("url") or item.get("title") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

    def _needs_academic_search(self, query: str, plan: PaperTaskPlan, memory_context: str = "") -> bool:
        text = f"{query}\n{memory_context}\n{plan.task_type}\n{plan.reason}".lower()
        terms = [
            "论文", "文献", "研究现状", "研究背景", "相关工作", "研究空白", "引用", "参考文献", "参考论文", "依据",
            "paper", "papers", "survey", "related work", "literature review", "citation", "reference",
        ]
        return plan.task_type in {"literature_review", "opening_report"} or any(term in text for term in terms)

    def _needs_web_search(self, query: str) -> bool:
        lowered = (query or "").lower()
        terms = [
            "官网", "官方", "政策", "公告", "报告", "github", "新闻", "行业资料", "行业", "公司", "产品", "文档",
            "official", "policy", "announcement", "report", "news", "industry",
        ]
        return any(term in lowered for term in terms)

    def _citation_label(self, item: Dict[str, Any], index: int) -> str:
        return f"[{index}]"

    def _citation_description(self, item: Dict[str, Any]) -> str:
        parts = [part for part in [item.get("authors"), str(item.get("year") or ""), item.get("source")] if part]
        meta = ". ".join(parts)
        snippet = item.get("snippet") or ""
        return f"{meta}. {snippet}".strip(". ")

    def _web_search_requested(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in ["联网", "搜索", "上网查", "web search", "search", "补充内容"])

    def _is_contextual_web_followup(self, query: str) -> bool:
        text = (query or "").strip()
        if not self._web_search_requested(text):
            return False
        lowered = text.lower()
        contextual_markers = [
            "这个选题", "该选题", "这个方向", "该方向", "上述主题", "上面这个", "前面这个", "这个研究",
            "相关论文", "相关文献", "参考论文", "联网搜", "联网搜索", "重点找", "最新研究", "最新论文",
        ]
        if any(marker in lowered for marker in contextual_markers):
            return True
        content_terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[一-龥]{2,8}", text)
        weak_terms = {
            "帮我", "联网", "补充", "继续", "搜索", "查找", "查一下", "搜一下", "内容", "一下",
            "这个", "该选题", "选题", "相关", "论文", "文献", "重点", "重点找", "优先", "最新", "研究",
            "以后", "以来", "之后", "近期", "当前",
        }
        meaningful = [term for term in content_terms if term.lower() not in weak_terms]
        return len(text) <= 20 or len(meaningful) <= 1

    def _contextual_topic_from_history(self, memory_context: str, recent_history: List[dict]) -> str:
        explicit = self._extract_explicit_focus(memory_context)
        if explicit:
            return explicit
        for msg in reversed(recent_history or []):
            if msg.get("role") != "user":
                continue
            content = (msg.get("content") or "").strip()
            if not content or self._is_contextual_web_followup(content):
                continue
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

    def _should_prompt_web_supplement(self, query: str, grade, context_text: str) -> bool:
        if self._web_search_requested(query):
            return False
        external_terms = ["依据", "证据", "文献", "论文", "研究现状", "研究背景", "研究空白", "最新", "当前", "近三年", "可靠吗", "可靠性"]
        lowered = (query or "").lower()
        needs_external = any(term in lowered for term in external_terms)
        low_evidence = not grade.sufficient or grade.coverage_score < 0.65 or len(context_text or "") < 400
        return low_evidence and needs_external

    def _append_web_supplement_prompt(self, answer: str, grade) -> str:
        missing = "、".join(grade.missing_aspects[:3]) if grade.missing_aspects else "外部论文、政策、报告或官网证据"
        prompt = (
            "\n\n---\n"
            "证据提示：当前内容主要基于本地论文库和对话上下文，外部联网证据仍不充分。"
            f"如果你需要更严谨的写作支撑，我可以继续联网补充：{missing}，"
            "然后基于最新论文、官网、政策或行业报告重新完善这一版。"
        )
        return (answer or "").rstrip() + prompt

    def _web_enrichment_query(self, query: str, memory_context: str, plan: PaperTaskPlan, recent_history: List[dict] | None = None) -> str:
        is_followup = self._is_contextual_web_followup(query)
        topic = self._contextual_topic_from_history(memory_context, recent_history or []) if is_followup else ""
        topic = topic or self._extract_explicit_focus(memory_context) or query
        constraints = self._academic_constraints(query)
        if constraints:
            topic = f"{topic}\n{constraints}"
        if plan.task_type == "opening_report":
            return self._compact_research_queries(topic)
        base = topic if is_followup else f"{query}\n{topic}"
        return self._compact_research_queries(base)

    def _academic_constraints(self, query: str) -> str:
        constraints = []
        if self._is_recent_required(query):
            constraints.append("2024-2026 latest recent studies")
        lowered = (query or "").lower()
        if any(term in lowered for term in ["相关论文", "相关文献", "参考论文", "related papers", "related work"]):
            constraints.append("related papers literature review")
        return " ".join(constraints)

    def _is_recent_required(self, query: str) -> bool:
        lowered = (query or "").lower()
        return any(term in lowered for term in ["2024", "2025", "2026", "最新", "近期", "当前", "以后", "以来", "之后", "recent", "latest", "since", "after"])

    def _extract_explicit_focus(self, memory_context: str) -> str:
        if not memory_context:
            return ""
        marker = "【显式指代解析】"
        if marker in memory_context:
            return memory_context.split(marker, 1)[1][:1200]
        return ""

    def _compact_research_queries(self, text: str) -> str:
        lowered = (text or "").lower()
        queries = []
        if any(term in lowered for term in ["multi-agent", "multi agent", "多agent", "多智能体", "agent"]):
            if any(term in lowered for term in ["医学", "医疗", "临床", "medical", "biomed", "biomedical", "clinical", "文献阅读", "论文阅读", "literature reading"]):
                queries.extend([
                    '"multi-agent RAG" medical literature review',
                    '"multi-agent" retrieval augmented generation biomedical literature',
                    '"RAG" "medical literature" "multi-agent"',
                    '医学论文 阅读 多智能体 RAG 证据',
                ])
            if any(term in lowered for term in ["2024", "2025", "2026", "最新", "近期", "当前", "以后", "以来"]):
                queries.extend([
                    '"multi-agent RAG" medical literature review 2024',
                    '"multi-agent" "retrieval augmented generation" biomedical 2024',
                    '"agentic RAG" biomedical literature 2024',
                ])
            queries.extend([
                '"LLM multi-agent" communication protocol semantic compression',
                '"multi-agent" "communication" "large language models"',
                '多智能体 协作 通信协议 语义压缩',
            ])
        if any(term in lowered for term in ["semantic", "语义", "compression", "压缩", "通信"]):
            queries.extend([
                '"semantic communication" multi-agent systems collaboration',
                '"communication efficiency" LLM agents protocol',
                '大语言模型 多智能体 通信效率',
            ])
        if any(term in lowered for term in ["元通信", "meta communication", "元动作", "意图"]):
            queries.extend([
                '"agent communication" "intent" "protocol"',
                '"meta communication" multi-agent systems',
            ])
        if not queries:
            keywords = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[一-龥]{2,8}", text or "")[:8]
            queries = [" ".join(keywords) or (text or "")[:120]]
        unique = []
        seen = set()
        for item in queries:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return " || ".join(unique[:8])

    def _format_web_context(self, web_evidence: List[Dict[str, Any]]) -> str:
        if not web_evidence:
            return ""
        lines = []
        for index, item in enumerate(web_evidence[:8], start=1):
            label = item.get("citation") or self._citation_label(item, index)
            meta = []
            if item.get("authors"):
                meta.append(str(item.get("authors")))
            if item.get("year"):
                meta.append(str(item.get("year")))
            if item.get("source"):
                meta.append(str(item.get("source")))
            if item.get("paper_id"):
                meta.append(f"paper_id={item.get('paper_id')}")
            if item.get("provider"):
                meta.append(f"provider={item.get('provider')}")
            meta_text = f" [{' | '.join(meta)}]" if meta else ""
            lines.append(f"- {label} {item.get('title')}{meta_text}: {item.get('snippet')} ({item.get('url')})")
        return "\n".join(lines)

    def _ensure_reference_links(self, answer: str, web_evidence: List[Dict[str, Any]]) -> str:
        if not web_evidence:
            return answer or ""
        if "http://" in (answer or "") or "https://" in (answer or ""):
            return answer or ""
        lines = ["", "### 引用链接"]
        for index, item in enumerate(web_evidence[:8], start=1):
            url = item.get("url")
            if not url:
                continue
            label = item.get("citation") or self._citation_label(item, index)
            title = item.get("title") or "外部论文"
            authors = item.get("authors") or "作者未知"
            year = item.get("year") or "年份未知"
            lines.append(f"- {label} {title}. {authors}. {year}. {url}")
        if len(lines) == 2:
            return answer or ""
        return (answer or "").rstrip() + "\n" + "\n".join(lines)

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
            "opening_report": ["abstract", "introduction", "method"],
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
            "opening_report": 10,
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

    def _format_external_sources(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sources = []
        for index, item in enumerate(items[:8], start=1):
            citation = item.get("citation") or self._citation_label(item, index)
            sources.append({
                "id": item.get("paper_id") or item.get("url") or item.get("id") or index,
                "name": item.get("title") or "外部证据",
                "type": item.get("result_type", "web_evidence"),
                "source": item.get("source"),
                "url": item.get("url"),
                "authors": item.get("authors"),
                "year": item.get("year"),
                "paper_id": item.get("paper_id"),
                "provider": item.get("provider"),
                "citation": citation,
                "description": item.get("description") or self._citation_description(item),
            })
        return sources

    def _merge_sources(self, primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
        merged = []
        seen = set()
        for item in primary + secondary:
            key = f"{item.get('type')}:{item.get('id') or item.get('url') or item.get('name')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged

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
