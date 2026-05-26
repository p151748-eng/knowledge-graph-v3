"""
SelfRAGPipeline: 本地检索、证据评估、检索修正、联网验证与答案校验编排。
"""

import asyncio
import time
from dataclasses import asdict
from typing import Any, AsyncGenerator, Dict, List
from sqlalchemy.orm import Session

from agents.answer_verifier import AnswerVerifierAgent
from agents.evidence_grader import EvidenceGraderAgent
from agents.retrieval_repair import RetrievalRepairAgent
from agents.web_verifier import WebSearchVerifierAgent
from config import config
from core.agent import AgentResult
from core.context import AgentContext
from models.schemas import IntegrationData, RetrievalAttemptData, RetrievalData
from tools.hybrid_search import HybridSearchTool


SELF_RAG_ANSWER_PROMPT = """你是一个严谨的 Self-RAG 问答助手。只能基于证据回答，不要编造。

【用户问题】
{query}

【对话记忆】
{memory_context}

【本地证据】
{local_context}

【联网证据】
{web_context}

【要求】
1. 优先使用对话记忆保持当前焦点和指代一致；本地证据为主要依据，联网证据只作为补充验证。
2. 如果证据不足，请明确说明不足之处。
3. 引用联网证据时标注网页标题和 URL。
4. 回答结构清晰、简洁。
"""


class SelfRAGPipeline:
    """CRAG + Web Verify 版 Self-RAG 编排器"""

    def __init__(self, db: Session, llm=None, allow_web: bool = True, persist_web: bool = False):
        from llm.manager import llm_manager
        self.db = db
        self.llm = llm if llm is not None else llm_manager
        self.allow_web = allow_web and config.CRAG_ALLOW_WEB
        self.persist_web = persist_web and config.CRAG_WEB_SAVE_ENABLED
        self.retriever = HybridSearchTool(db, self.llm)
        self.grader = EvidenceGraderAgent(self.llm)
        self.repairer = RetrievalRepairAgent(self.llm)
        self.web_verifier = WebSearchVerifierAgent(db, self.llm)
        self.answer_verifier = AnswerVerifierAgent(self.llm)

    def run(self, context: AgentContext) -> AgentResult:
        query = context.pipeline_data.query
        memory_context = context.extra.get("memory_context", "") if context.extra else ""
        if memory_context:
            query_for_retrieval = f"{query}\n\n{memory_context}"
        else:
            query_for_retrieval = query
        attempts: List[RetrievalAttemptData] = []

        retrieval = self.retriever.execute(query_for_retrieval, top_k=10)
        grade = self.grader.grade(query, retrieval, round_index=1)
        attempts.append(self._attempt(1, query, retrieval, grade, "local"))

        final_retrieval = retrieval
        final_grade = grade
        local_query = query
        if not grade.sufficient and grade.next_action in {"rewrite_local", "adjust_strategy"} and config.CRAG_MAX_LOCAL_ROUNDS >= 2:
            repair = self.repairer.repair(query, retrieval, grade)
            local_query = repair.get("rewritten_query") or query
            override = repair.get("strategy", {}).copy()
            override["optimized_query"] = local_query
            override["expanded_queries"] = repair.get("expanded_queries", [])
            repaired = self.retriever.execute(local_query, top_k=10, plan_override=override)
            repaired_grade = self.grader.grade(local_query, repaired, round_index=2)
            if repaired_grade.sufficient and grade.next_action in {"rewrite_local", "adjust_strategy"}:
                repaired_grade.next_action = "answer"
            attempts.append(self._attempt(2, local_query, repaired, repaired_grade, "local"))
            final_retrieval = repaired
            final_grade = repaired_grade

        web_evidence: List[Dict[str, Any]] = []
        needs_external_verification = self._needs_external_verification(query)
        if self.allow_web and (
            (final_grade.next_action == "web_verify" or final_grade.freshness_required or needs_external_verification)
            and (not final_grade.sufficient or needs_external_verification)
        ):
            web_evidence = self.web_verifier.search_and_grade(local_query, final_grade)
            context.pipeline_data.web_evidence = web_evidence
            attempts.append(RetrievalAttemptData(
                round=len(attempts) + 1,
                query=local_query,
                strategy={"web": True, "max_results": config.CRAG_WEB_MAX_RESULTS, "save": self.persist_web},
                retrieval={"web_evidence": web_evidence},
                grade=final_grade,
                source="web",
            ))

        answer = self._generate_answer(query, final_retrieval, web_evidence, memory_context)
        verification = self.answer_verifier.verify(query, answer, final_retrieval.get("context_text", ""), web_evidence)
        if verification.get("final_action") == "refuse":
            answer = "当前本地知识库和联网验证都没有提供足够可靠的证据，暂时无法给出有支撑的回答。"

        context.pipeline_data.retrieval_attempts = attempts
        context.pipeline_data.evidence_grade = final_grade
        context.pipeline_data.retrieval_data = RetrievalData(
            entities=[item for item in final_retrieval.get("merged", []) if item.get("result_type") != "chunk"],
            relations=final_retrieval.get("graph_hits", []),
            context_text=final_retrieval.get("context_text", ""),
            doc_chunks=final_retrieval.get("bm25_hits", []) + final_retrieval.get("semantic_hits", []),
        )
        sources = self._sources(final_retrieval, web_evidence)
        integration = IntegrationData(
            answer=answer,
            sources=sources,
            confidence=verification.get("support_score", final_grade.coverage_score),
            key_points=[],
        )
        context.pipeline_data.integration_data = integration
        context.pipeline_data.answer_verification = verification

        return AgentResult(
            success=True,
            output={
                "answer": answer,
                "sources": sources,
                "web_sources": [item for item in sources if item.get("type") == "web"],
                "retrieval_rounds": [self._attempt_dict(item) for item in attempts],
                "evidence_grade": asdict(final_grade),
                "answer_verification": verification,
                "confidence": integration.confidence,
            },
            message="Self-RAG 执行完成",
            confidence=integration.confidence,
        )

    async def run_async(self, context: AgentContext) -> AsyncGenerator[dict, None]:
        loop = asyncio.get_running_loop()
        start = time.time()
        yield {"type": "status", "agent": "SelfRAG", "step": "检索与证据评估中", "elapsed": 0.0}
        result = await loop.run_in_executor(None, self.run, context)
        elapsed = time.time() - start
        if not result.success:
            yield {"type": "error", "message": result.message}
            return
        output = result.output or {}
        yield {"type": "sources", "data": output.get("sources", [])}
        for char in output.get("answer", ""):
            yield {"type": "delta", "content": char}
        yield {"type": "metrics", "path": "self_rag", "processing_time": f"{elapsed:.1f}s", "confidence": output.get("confidence", 0.5)}

    def _needs_external_verification(self, query: str) -> bool:
        lowered = (query or "").lower()
        verification_terms = ["验证", "证据", "是否充分", "可靠吗", "可靠性", "依据", "paper", "论文", "benchmark", "评测"]
        method_terms = ["self-rag", "crag", "graphrag"]
        return any(term in lowered for term in verification_terms) and any(term in lowered for term in method_terms)

    def _generate_answer(self, query: str, retrieval: Dict[str, Any], web_evidence: List[Dict[str, Any]], memory_context: str = "") -> str:
        web_context = "\n".join([f"- {item.get('title')}: {item.get('snippet')} ({item.get('url')})" for item in web_evidence])
        prompt = SELF_RAG_ANSWER_PROMPT.format(
            query=query,
            memory_context=memory_context or "（无对话记忆）",
            local_context=retrieval.get("context_text") or "（无本地证据）",
            web_context=web_context or "（无联网证据）",
        )
        try:
            return self.llm.complete(prompt).content
        except Exception as e:
            return f"[错误] LLM 调用失败: {str(e)}"

    def _attempt(self, round_index: int, query: str, retrieval: Dict[str, Any], grade, source: str) -> RetrievalAttemptData:
        return RetrievalAttemptData(
            round=round_index,
            query=query,
            strategy=retrieval.get("plan", {}),
            retrieval={
                "bm25_hits": len(retrieval.get("bm25_hits", [])),
                "semantic_hits": len(retrieval.get("semantic_hits", [])),
                "graph_hits": len(retrieval.get("graph_hits", [])),
                "merged": len(retrieval.get("merged", [])),
            },
            grade=grade,
            source=source,
        )

    def _attempt_dict(self, attempt: RetrievalAttemptData) -> Dict[str, Any]:
        data = asdict(attempt)
        if attempt.grade:
            data["grade"] = asdict(attempt.grade)
        return data

    def _sources(self, retrieval: Dict[str, Any], web_evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sources = []
        for item in retrieval.get("merged", [])[:5]:
            if item.get("result_type") in {"chunk", "document"}:
                sources.append({
                    "id": item.get("chunk_id") or item.get("id") or 0,
                    "name": item.get("title", "文档片段"),
                    "type": "document",
                    "description": (item.get("content") or "")[:160],
                })
            else:
                sources.append({
                    "id": item.get("node_id") or item.get("edge_id") or item.get("id") or 0,
                    "name": item.get("name") or item.get("description") or "图谱证据",
                    "type": item.get("type", "entity"),
                    "description": item.get("description"),
                })
        for item in web_evidence:
            sources.append({
                "id": item.get("id", 0),
                "name": item.get("title", "联网证据"),
                "type": "web",
                "description": item.get("snippet"),
                "url": item.get("url"),
            })
        return sources
