import asyncio
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from agents.citation_verifier import CitationVerifier
from agents.paper_assistant import PaperAssistantAgent
from agents.pipeline import AgentPipeline
from agents.planned_workflow import ResearchWorkflow
from agents.self_rag_pipeline import SelfRAGPipeline
from core.context import AgentContext
from core.graph_state import WorkflowState
from core.orchestrator import BaseWorkflow, WorkflowRegistry, WorkflowResult
from tools.hybrid_search import HybridSearchTool


FAST_PROMPT = "你是一个知识问答助手。回答问题时：1) 优先参考对话记忆中的当前焦点、摘要和相关历史片段；2) 结合以下知识库内容补充信息；3) 如果知识库中没有相关内容但对话记忆中有，直接使用记忆中的信息。"


class FastQAWorkflow(BaseWorkflow):
    path = "fast"

    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        query = context.pipeline_data.query
        retrieval = HybridSearchTool(self.db, self.llm).execute(query, top_k=5)
        context_text = retrieval.get("context_text") or self._fallback_context(retrieval.get("merged", []))
        memory_context = (context.extra or {}).get("memory_context", "")
        system_prompt = FAST_PROMPT + (("\n" + context_text) if context_text else "") + memory_context
        history = (context.extra or {}).get("recent_history", [])
        try:
            answer = self.llm.complete(query, system_prompt, history=history).content
            confidence = 0.7
        except TypeError:
            try:
                answer = self.llm.complete(query, system_prompt).content
                confidence = 0.7
            except Exception as exc:
                answer = f"[错误] LLM 调用失败: {exc}"
                confidence = 0.0
        except Exception as exc:
            answer = f"[错误] LLM 调用失败: {exc}"
            confidence = 0.0
        elapsed = time.time() - start
        evidence_state = WorkflowState(query=query)
        evidence_state.add_evidence_from_retrieval(retrieval)
        citation_verification = CitationVerifier(self.llm).verify(query, answer, evidence_state.evidence_items)
        return WorkflowResult(
            success=not answer.startswith("[错误]"),
            path="fast",
            response=answer,
            sources=self._format_sources(retrieval.get("merged", [])[:5]),
            confidence=confidence,
            processing_time=f"{elapsed:.1f}s",
            metadata={
                "evidence_items": evidence_state.evidence_dicts(),
                "citation_verification": citation_verification,
            },
        )

    async def run_async(self, context: AgentContext, decision=None) -> AsyncGenerator[dict, None]:
        start = time.time()
        yield {"type": "status", "agent": "FastPath", "step": "检索中", "elapsed": 0.0}
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.run, context, decision)
        yield {"type": "sources", "data": result.sources}
        for char in result.response:
            yield {"type": "delta", "content": char}
        yield {"type": "status", "agent": "FastPath", "step": "完成", "elapsed": time.time() - start}
        yield {"type": "metrics", "path": "fast", "processing_time": result.processing_time, "confidence": result.confidence}

    def _fallback_context(self, items: list) -> str:
        return "\n".join([
            f"【{item.get('type', item.get('result_type', '证据'))}】{item.get('name') or item.get('title')}: {item.get('description') or item.get('content', '')}"
            for item in items[:3]
        ])

    def _format_sources(self, items: list) -> list:
        sources = []
        for item in items:
            result_type = item.get("result_type")
            if result_type in {"chunk", "document"}:
                sources.append({
                    "id": item.get("chunk_id") or item.get("id"),
                    "name": item.get("title", "文档片段"),
                    "type": "document",
                    "description": (item.get("content") or "")[:160],
                    "chunk_type": item.get("chunk_type") or item.get("section_type"),
                    "source": item.get("source"),
                })
            else:
                sources.append({
                    "id": item.get("node_id") or item.get("edge_id") or item.get("id"),
                    "name": item.get("name") or item.get("description") or "图谱证据",
                    "type": item.get("type", "entity"),
                    "description": item.get("description"),
                })
        return sources


class KGPipelineWorkflow(BaseWorkflow):
    path = "pipeline"

    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        pipeline = self._pipeline()
        result = pipeline.run(context)
        elapsed = time.time() - start
        if result.success and result.output:
            pd = context.pipeline_data
            integration = pd.integration_data
            return WorkflowResult(
                success=True,
                path="pipeline",
                response=integration.answer if integration else result.output.get("answer", ""),
                sources=self._pipeline_sources(integration.sources if integration else result.output.get("sources", [])),
                explanations=pd.explanation_data.explanations if pd.explanation_data else [],
                confidence=integration.confidence if integration else result.output.get("confidence", 0.5),
                processing_time=f"{elapsed:.1f}s",
            )
        return WorkflowResult(False, "pipeline", response=f"[错误] 流水线执行失败: {result.message}", confidence=0.0, processing_time=f"{elapsed:.1f}s", message=result.message)

    async def run_async(self, context: AgentContext, decision=None) -> AsyncGenerator[dict, None]:
        async for event in self._pipeline().run_async(context):
            yield event

    def _pipeline(self) -> AgentPipeline:
        pipeline = AgentPipeline(self.db)
        pipeline.retriever.search_tool.embedding_service = self.llm
        pipeline.explainer.llm = self.llm
        pipeline.integrator.llm = self.llm
        return pipeline

    def _pipeline_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{"id": item.get("id"), "name": item.get("name"), "type": item.get("type", "entity"), "description": item.get("description")} for item in sources]


class SelfRAGWorkflow(BaseWorkflow):
    path = "self_rag"

    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        result = SelfRAGPipeline(self.db, self.llm, allow_web=True).run(context)
        elapsed = time.time() - start
        if result.success and result.output:
            output = result.output
            evidence_state = WorkflowState(query=context.pipeline_data.query)
            for source in output.get("sources", []):
                evidence_state.add_evidence_from_retrieval({"merged": [{**source, "result_type": source.get("type", "source"), "content": source.get("description") or source.get("name", "")}]})
            citation_verification = CitationVerifier(self.llm).verify(context.pipeline_data.query, output.get("answer", ""), evidence_state.evidence_items)
            return WorkflowResult(
                True,
                "self_rag",
                response=output.get("answer", ""),
                sources=output.get("sources", []),
                explanations=[],
                confidence=output.get("confidence", result.confidence),
                processing_time=f"{elapsed:.1f}s",
                metadata={
                    "web_sources": output.get("web_sources", []),
                    "retrieval_rounds": output.get("retrieval_rounds", []),
                    "evidence_grade": output.get("evidence_grade", {}),
                    "answer_verification": output.get("answer_verification", {}),
                    "evidence_items": evidence_state.evidence_dicts(),
                    "citation_verification": citation_verification,
                },
            )
        return WorkflowResult(False, "self_rag", response=f"[错误] Self-RAG 执行失败: {result.message}", confidence=0.0, processing_time=f"{elapsed:.1f}s")

    async def run_async(self, context: AgentContext, decision=None) -> AsyncGenerator[dict, None]:
        async for event in SelfRAGPipeline(self.db, self.llm).run_async(context):
            yield event


class PaperAssistantWorkflow(BaseWorkflow):
    path = "paper_assistant"

    def run(self, context: AgentContext, decision=None) -> WorkflowResult:
        start = time.time()
        result = PaperAssistantAgent(self.db, self.llm).run(context)
        elapsed = time.time() - start
        if result.success and result.output:
            output = result.output
            evidence_state = WorkflowState(query=context.pipeline_data.query)
            for source in output.get("sources", []):
                evidence_state.add_evidence_from_retrieval({"merged": [{**source, "result_type": source.get("type", "source"), "content": source.get("description") or source.get("name", "")}]})
            citation_verification = CitationVerifier(self.llm).verify(context.pipeline_data.query, output.get("answer", ""), evidence_state.evidence_items)
            return WorkflowResult(
                True,
                "paper_assistant",
                response=output.get("answer", ""),
                sources=output.get("sources", []),
                explanations=[],
                confidence=output.get("confidence", result.confidence),
                processing_time=f"{elapsed:.1f}s",
                metadata={
                    "paper_task": output.get("paper_task", {}),
                    "retrieval_plan": output.get("retrieval_plan", {}),
                    "evidence_grade": output.get("evidence_grade", {}),
                    "retrieval_rounds": output.get("retrieval_rounds", []),
                    "performance": output.get("performance", {}),
                    "evidence_items": evidence_state.evidence_dicts(),
                    "citation_verification": citation_verification,
                },
            )
        return WorkflowResult(False, "paper_assistant", response=f"[错误] 论文参考助手执行失败: {result.message}", confidence=0.0, processing_time=f"{elapsed:.1f}s")

    async def run_async(self, context: AgentContext, decision=None) -> AsyncGenerator[dict, None]:
        yield {"type": "status", "agent": "PaperAssistant", "step": "论文任务分析中", "elapsed": 0.0}
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self.run, context, decision)
        yield {"type": "sources", "data": result.sources}
        for char in result.response:
            yield {"type": "delta", "content": char}
        yield {"type": "metrics", "path": "paper_assistant", "processing_time": result.processing_time, "confidence": result.confidence, **result.metadata}


def create_default_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    registry.register("fast", FastQAWorkflow)
    registry.register("pipeline", KGPipelineWorkflow)
    registry.register("self_rag", SelfRAGWorkflow)
    registry.register("paper_assistant", PaperAssistantWorkflow)
    registry.register("research", ResearchWorkflow)
    return registry
