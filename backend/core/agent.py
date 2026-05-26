"""
BaseAgent: 所有 Agent 的抽象基类。
定义了 Agent 的生命周期、工具绑定和执行接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    output: Any = None
    message: str = ""
    confidence: float = 0.5
    errors: List[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Agent 抽象基类"""

    def __init__(self, name: str, role: str, description: str = ""):
        self.name = name
        self.role = role
        self.description = description
        self.status = AgentStatus.IDLE
        self._tools: Dict[str, Any] = {}

    def bind_tools(self, tool_names: List[str]) -> None:
        """绑定工具（子类或外部调用）"""
        from tools.registry import ToolRegistry

        registry = ToolRegistry()
        for name in tool_names:
            tool = registry.get(name)
            if tool:
                self._tools[name] = tool

    def use_tool(self, name: str, **kwargs) -> Dict[str, Any]:
        """执行工具"""
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not bound"}
        return tool.execute(**kwargs)

    @abstractmethod
    def execute(self, context: "AgentContext") -> AgentResult:
        """执行 Agent 逻辑，子类必须实现"""
        pass

    def run(self, context: "AgentContext") -> AgentResult:
        """运行 Agent"""
        self.status = AgentStatus.WORKING
        try:
            result = self.execute(context)
            self.status = AgentStatus.COMPLETED
            return result
        except Exception as e:
            self.status = AgentStatus.ERROR
            return AgentResult(
                success=False,
                output=None,
                message=str(e),
                errors=[str(e)]
            )
