"""
ChatService: unified orchestration entrypoint.
"""

from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.orm import Session

from agents.workflows import create_default_workflow_registry
from core.context import AgentContext, PipelineData
from core.orchestrator import WorkflowResult, WorkflowRunner
from core.router import ContextAwareRouter, RouteDecision, RouteInput
from llm.manager import llm_manager
from models.db import Conversation
from services.memory import MemoryService, RECENT_HISTORY_ROUNDS

MAX_HISTORY_ROUNDS = RECENT_HISTORY_ROUNDS


class ChatService:
    """对话服务 - 统一路由与工作流编排入口。"""

    def __init__(self, db: Session):
        self.db = db
        self.router = ContextAwareRouter()
        self.llm = llm_manager
        self.workflow_registry = create_default_workflow_registry()
        self.workflow_runner = WorkflowRunner(self.workflow_registry)

    def chat(self, message: str, conversation_id: Optional[int] = None, force_path: Optional[str] = None) -> Dict[str, Any]:
        history = self._load_history(conversation_id)
        memory_context = self._build_history_prompt(conversation_id, message)
        decision = self._route(message, force_path, history, memory_context)
        context = self._build_context(message, history, memory_context, decision)
        result = self.workflow_runner.run(self.db, self.llm, context, decision)
        conv = self._save_result(message, result, conversation_id, decision)
        return result.to_chat_dict(conv.id if conv else (conversation_id or 0))

    def chat_fast_path(self, message: str, conversation_id: Optional[int] = None) -> Dict[str, Any]:
        return self.chat(message, conversation_id, "fast")

    def chat_pipeline(self, message: str, conversation_id: Optional[int] = None) -> Dict[str, Any]:
        return self.chat(message, conversation_id, "pipeline")

    def chat_paper_assistant(self, message: str, conversation_id: Optional[int] = None) -> Dict[str, Any]:
        return self.chat(message, conversation_id, "paper_assistant")

    def chat_self_rag(self, message: str, conversation_id: Optional[int] = None, allow_web: bool = True) -> Dict[str, Any]:
        return self.chat(message, conversation_id, "self_rag")

    async def stream_chat(self, message: str, conversation_id: Optional[int] = None, force_path: Optional[str] = None) -> AsyncGenerator[dict, None]:
        history = self._load_history(conversation_id)
        memory_context = self._build_history_prompt(conversation_id, message)
        decision = self._route(message, force_path, history, memory_context)
        context = self._build_context(message, history, memory_context, decision)
        full_answer_parts: List[str] = []
        last_metrics: Dict[str, Any] = {}

        yield {"type": "route", "data": decision.to_dict()}
        async for event in self.workflow_runner.run_async(self.db, self.llm, context, decision):
            if event.get("type") == "delta":
                full_answer_parts.append(event.get("content", ""))
            if event.get("type") == "metrics":
                last_metrics = event
            yield event

        full_answer = "".join(full_answer_parts)
        result = self._result_from_context(decision, context, full_answer, last_metrics)
        conv = self._save_result(message, result, conversation_id, decision)
        yield {"type": "conversation_id", "conversation_id": conv.id if conv else (conversation_id or 0)}

    def _route(self, message: str, force_path: Optional[str], history: List[dict], memory_context: str) -> RouteDecision:
        return self.router.route(RouteInput(
            query=message,
            force_path=force_path,
            recent_turns=history,
            memory_context=memory_context,
            last_route=self._last_route_decision(history),
        ))

    def _build_context(self, message: str, history: List[dict], memory_context: str, decision: RouteDecision) -> AgentContext:
        context = AgentContext(pipeline_data=PipelineData(query=message))
        context.extra["recent_history"] = history
        context.extra["memory_context"] = memory_context
        context.extra["route_decision"] = decision.to_dict()
        return context

    def _result_from_context(self, decision: RouteDecision, context: AgentContext, answer: str, metrics: Dict[str, Any]) -> WorkflowResult:
        pd = context.pipeline_data
        sources = []
        explanations = []
        metadata = {key: value for key, value in metrics.items() if key not in {"type", "path", "processing_time", "confidence"}}
        if pd.integration_data:
            sources = pd.integration_data.sources or []
            if not answer:
                answer = pd.integration_data.answer
        if pd.explanation_data:
            explanations = pd.explanation_data.explanations or []
        return WorkflowResult(
            success=not answer.startswith("[错误]"),
            path=decision.path,
            response=answer,
            sources=sources,
            explanations=explanations,
            confidence=metrics.get("confidence", pd.integration_data.confidence if pd.integration_data else 0.5),
            processing_time=metrics.get("processing_time", "0.0s"),
            metadata=metadata,
        )

    def _load_history(self, conversation_id: Optional[int]) -> List[dict]:
        try:
            return MemoryService(self.db, self.llm).load_recent_turns(conversation_id, rounds=RECENT_HISTORY_ROUNDS)
        except Exception:
            if not conversation_id:
                return []
            try:
                conv = self.db.query(Conversation).filter(Conversation.id == conversation_id).first()
                if not conv or not conv.messages:
                    return []
                history = conv.messages[-(RECENT_HISTORY_ROUNDS * 2):]
                return [self._history_item(item) for item in history]
            except Exception:
                return []

    def _history_item(self, item: dict) -> dict:
        return {
            "role": item.get("role"),
            "content": item.get("content", ""),
            "path": item.get("path"),
            "intent": item.get("intent"),
            "route_decision": item.get("route_decision"),
        }

    def _build_history_prompt(self, conversation_id: Optional[int], message: str = "") -> str:
        if not conversation_id:
            return ""
        try:
            return MemoryService(self.db, self.llm).build_memory_context(message, conversation_id).get("prompt_text", "")
        except Exception:
            history = self._load_history(conversation_id)
            if not history:
                return ""
            lines = ["\n\n【对话记忆】以下是最近对话内容，回答时保持上下文连贯："]
            for msg in history:
                role_label = "用户" if msg.get("role") == "user" else "助手"
                lines.append(f"{role_label}: {msg.get('content', '')[:500]}")
            return "\n".join(lines)

    def _last_route_decision(self, history: List[dict]) -> Optional[Dict[str, Any]]:
        for item in reversed(history or []):
            if item.get("role") == "assistant":
                if item.get("route_decision"):
                    return item["route_decision"]
                if item.get("path"):
                    return {"path": item.get("path"), "intent": item.get("intent", "followup")}
        return None

    def _save_result(
        self,
        user_message: str,
        result: WorkflowResult,
        conversation_id: Optional[int],
        decision: RouteDecision,
    ) -> Optional[Conversation]:
        return self._save_conversation(
            user_message,
            result.response,
            conversation_id,
            path=result.path,
            sources=result.sources,
            explanations=result.explanations,
            route_decision=decision.to_dict(),
            metadata=result.metadata,
        )

    def _save_conversation(
        self,
        user_message: str,
        assistant_message: str,
        conversation_id: Optional[int],
        path: str = "fast",
        sources: list = None,
        explanations: list = None,
        route_decision: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Conversation]:
        try:
            if conversation_id:
                conv = self.db.query(Conversation).filter(Conversation.id == conversation_id).first()
            else:
                conv = None

            if conv is None:
                conv = Conversation(title=user_message[:50], messages=[])
                self.db.add(conv)
                self.db.flush()

            messages = conv.messages or []
            timestamp = datetime.utcnow().isoformat()
            messages.append({"role": "user", "content": user_message, "timestamp": timestamp})
            assistant_payload = {
                "role": "assistant",
                "content": assistant_message,
                "timestamp": timestamp,
                "path": path,
                "sources": sources or [],
                "explanations": explanations or [],
            }
            if route_decision:
                assistant_payload["route_decision"] = route_decision
                assistant_payload["intent"] = route_decision.get("intent")
            if metadata:
                assistant_payload["workflow_metadata"] = metadata
            messages.append(assistant_payload)

            from sqlalchemy.orm.attributes import flag_modified
            conv.messages = messages
            flag_modified(conv, "messages")
            self.db.commit()
            self.db.refresh(conv)
            try:
                MemoryService(self.db, self.llm).update_after_turn(conv.id, async_update=True)
            except Exception:
                pass
            return conv
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass
            return None
