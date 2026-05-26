"""
BaseTool: 所有工具的抽象基类。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """工具抽象基类"""

    name: str = "base_tool"
    description: str = ""

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """执行工具逻辑，子类必须实现"""
        pass
