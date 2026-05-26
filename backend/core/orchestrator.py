from dataclasses import asdict, dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from core.agent import AgentResult
from core.context import AgentContext
from core.router import RouteDecision


@dataclass
class WorkflowEvent:
    type: str
    path: str = ""
    agent: str = ""
    step: str = ""
    elapsed: float = 0.0
    content: str = ""
    data: Any = None
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        event = {"type": self.type}
        for key, value in asdict(self).items():
            if key == "type":
                continue
            if value not in ("", None, [], {}):
                event[key] = value
        return event


@dataclass
class WorkflowResult:
    success: bool
    path: str
    response: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    explanations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    processing_time: str = "0.0s"
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)

    def to_chat_dict(self, conversation_id: int = 0) -> Dict[str, Any]:
        data = {
            "response": self.response,
            "sources": self.sources,
            "explanations": self.explanations,
            "conversation_id": conversation_id,
            "path": self.path,
            "processing_time": self.processing_time,
            "confidence": self.confidence,
        }
        data.update(self.metadata)
        return data


@dataclass
class WorkflowStage:
    name: str
    agent: str
    start_step: str
    done_step: str
    continue_on_error: bool = False


class BaseWorkflow:
    path = "base"

    def __init__(self, db, llm=None):
        self.db = db
        self.llm = llm

    def run(self, context: AgentContext, decision: Optional[RouteDecision] = None) -> WorkflowResult:
        raise NotImplementedError

    async def run_async(self, context: AgentContext, decision: Optional[RouteDecision] = None) -> AsyncGenerator[dict, None]:
        result = self.run(context, decision)
        if result.sources:
            yield {"type": "sources", "data": result.sources}
        for char in result.response:
            yield {"type": "delta", "content": char}
        yield {
            "type": "metrics",
            "path": result.path,
            "processing_time": result.processing_time,
            "confidence": result.confidence,
            **result.metadata,
        }


class WorkflowRegistry:
    def __init__(self):
        self._workflows = {}

    def register(self, path: str, workflow_cls):
        self._workflows[path] = workflow_cls

    def create(self, path: str, db, llm=None) -> BaseWorkflow:
        workflow_cls = self._workflows.get(path) or self._workflows.get("pipeline")
        return workflow_cls(db, llm)


class WorkflowRunner:
    def __init__(self, registry: WorkflowRegistry):
        self.registry = registry

    def run(self, db, llm, context: AgentContext, decision: RouteDecision) -> WorkflowResult:
        workflow = self.registry.create(decision.path, db, llm)
        return workflow.run(context, decision)

    async def run_async(self, db, llm, context: AgentContext, decision: RouteDecision) -> AsyncGenerator[dict, None]:
        workflow = self.registry.create(decision.path, db, llm)
        async for event in workflow.run_async(context, decision):
            yield event
