"""内存 ToolProvider —— 测试 / 未来内置扩展用。"""
from __future__ import annotations

import dataclasses
from typing import Iterable, List

from app.services.agent_runtime.providers.base import ToolProvider
from app.services.agent_runtime.tools import Tool


class StaticToolProvider(ToolProvider):
    """把传入的 Tool 以 `{name}__` 前缀暴露，保证 registry 命名空间隔离。"""

    def __init__(self, name: str, tools: Iterable[Tool]):
        self.name = name
        self._tools: List[Tool] = [self._namespace(t) for t in tools]

    def _namespace(self, tool: Tool) -> Tool:
        if tool.name.startswith(f"{self.name}__"):
            return tool
        return dataclasses.replace(tool, name=f"{self.name}__{tool.name}")

    def list_tools(self) -> List[Tool]:
        return list(self._tools)

    def add(self, tool: Tool) -> None:
        self._tools.append(self._namespace(tool))
