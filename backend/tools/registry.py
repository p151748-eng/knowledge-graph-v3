"""
工具注册表。Agent 通过 bind_tools() 获取所需工具。
"""

from typing import Any, Dict, Optional


class ToolRegistry:
    """全局工具注册中心"""

    _tools: Dict[str, Any] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, name: str, tool: Any) -> None:
        """注册工具"""
        cls._tools[name] = tool

    @classmethod
    def get(cls, name: str) -> Optional[Any]:
        """获取工具"""
        return cls._tools.get(name)

    @classmethod
    def list_tools(cls) -> list:
        """列出所有已注册工具"""
        return list(cls._tools.keys())
