"""ToolProvider —— 外部工具源扩展点。

一个 ToolProvider 向 ToolRegistry 贡献一组 Tool（MCP server、未来的内置扩展等）。
Provider 可在运行时注册 / 刷新 / 卸载，不重启服务。
"""
from app.services.agent_runtime.providers.base import ToolProvider
from app.services.agent_runtime.providers.static_provider import StaticToolProvider
from app.services.agent_runtime.providers.mcp_provider import MCPProvider, MCPError

__all__ = ["ToolProvider", "StaticToolProvider", "MCPProvider", "MCPError"]
