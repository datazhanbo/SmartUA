"""ToolProvider 抽象。

一个 Provider 向 ToolRegistry 贡献一组 Tool。Provider 自己负责工具的生命周期：
- list_tools() 每次 registry 刷新时被调用，返回当前可用的 Tool 列表
- close() 在卸载时释放连接（HTTP client、线程池等）

命名空间契约：
- 每个 Tool 的 `name` 必须以 `{provider.name}__` 开头，确保不同 provider 之间不冲突；
  registry 靠此前缀在 refresh/unregister 时清理已删除工具。

外部工具的风险分级由 Provider 决定，但必须遵守安全缺省：
- 只读工具默认 L0（自动执行）
- 写工具默认 L3（仅建议）—— 外部来源的写动作必须经人审，除非显式在配置里降级
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from app.services.agent_runtime.tools import Tool


class ToolProvider(ABC):
    """外部工具源。name 必须全局唯一，用作工具命名空间前缀。"""

    name: str = "provider"

    @abstractmethod
    def list_tools(self) -> List[Tool]:
        """返回当前可用工具（name 必须以 `{self.name}__` 开头）。"""
        raise NotImplementedError

    def close(self) -> None:
        """释放资源。默认无操作。"""
        return None
