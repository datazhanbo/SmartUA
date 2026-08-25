"""MCP (Model Context Protocol) streamable-http ToolProvider。

用 httpx 实现 JSON-RPC 2.0 握手（initialize → tools/list → tools/call），
把外部 MCP server 暴露的工具映射成本地 Tool。不引入 `mcp` SDK 依赖——当前只需
最小子集，等真要接 stdio / SSE 或资源/提示语能力时再考虑加。

安全缺省（与 plan 一致）：
- 只读工具（annotations.readOnlyHint=true 或名字以 get/list/search/observe/evaluate/read 开头）→ L0 / read
- 写工具默认 L3（仅建议）；可经 `tool_risk` 配置显式降级
- 连不上 server 时 list_tools() 返回空列表并记 warning（fail-soft，不拖垮 AgentLoop）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.services.agent_runtime.providers.base import ToolProvider
from app.services.agent_runtime.tools import (
    AgentContext, Tool, ToolResult,
)

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"

_READ_NAME_PREFIXES = ("get", "list", "search", "observe", "evaluate", "read", "query", "fetch", "lookup")


class MCPError(RuntimeError):
    pass


class MCPProvider(ToolProvider):
    """同步 MCP streamable-http provider。"""

    def __init__(
        self,
        name: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 15.0,
        tool_risk: Optional[Dict[str, str]] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.name = name
        self.url = url
        self._headers = {"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream",
                         **(headers or {})}
        self._timeout = timeout
        self._tool_risk = tool_risk or {}
        self._client = client
        self._owns_client = client is None
        self._session_id: Optional[str] = None
        self._initialized = False
        self._cache: Optional[List[Tool]] = None
        self._next_id = 0

    # ----------------------------- 生命周期 ----------------------------- #
    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, trust_env=True)
            self._owns_client = True
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    # ----------------------------- JSON-RPC ----------------------------- #
    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None,
             *, is_notification: bool = False) -> Optional[Dict[str, Any]]:
        client = self._ensure_client()
        self._next_id += 1
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not is_notification:
            payload["id"] = self._next_id

        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        resp = client.post(self.url, content=json.dumps(payload), headers=headers)
        # 某些 server 在 initialize 响应里回 Mcp-Session-Id
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        if is_notification:
            return None
        if resp.status_code >= 400:
            raise MCPError(f"{method} HTTP {resp.status_code}: {resp.text[:200]}")
        # streamable-http 可能返回 SSE；取第一条 data: 行
        ctype = resp.headers.get("content-type", "")
        body_text = resp.text
        if "text/event-stream" in ctype:
            for line in body_text.splitlines():
                if line.startswith("data:"):
                    body_text = line[5:].strip()
                    break
        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as e:
            raise MCPError(f"{method} 返回非 JSON: {body_text[:200]}") from e
        if "error" in data:
            err = data["error"]
            raise MCPError(f"{method} JSON-RPC error: {err.get('code')} {err.get('message')}")
        return data.get("result")

    def _initialize(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": f"smartua-{self.name}", "version": "1.0"},
        })
        self._rpc("notifications/initialized", is_notification=True)
        self._initialized = True

    # ----------------------------- ToolProvider ----------------------------- #
    def list_tools(self) -> List[Tool]:
        if self._cache is not None:
            return self._cache
        try:
            self._initialize()
            result = self._rpc("tools/list") or {}
        except Exception as e:
            logger.warning("MCPProvider[%s] 列出工具失败（返回空）：%s", self.name, e)
            return []
        tools: List[Tool] = []
        for spec in result.get("tools", []):
            tools.append(self._build_tool(spec))
        self._cache = tools
        return tools

    def refresh(self) -> List[Tool]:
        """强制重新拉取工具列表（不重启服务）。"""
        self._cache = None
        return self.list_tools()

    # ----------------------------- 工具映射 ----------------------------- #
    def _build_tool(self, spec: Dict[str, Any]) -> Tool:
        mcp_name = spec.get("name", "")
        local_name = f"{self.name}__{mcp_name}"
        desc = spec.get("description") or f"MCP tool {self.name}/{mcp_name}"
        schema = spec.get("inputSchema") or {}
        annotations = spec.get("annotations") or {}
        read_only = bool(annotations.get("readOnlyHint")) or self._looks_read_only(mcp_name)
        side_effect = "read" if read_only else "write"
        risk = self._tool_risk.get(mcp_name) or ("L0" if read_only else "L3")

        def handler(params: Dict[str, Any], ctx: AgentContext, _mcp_name=mcp_name) -> ToolResult:
            return self._call_tool(_mcp_name, params)

        return Tool(
            name=local_name,
            description=f"[MCP:{self.name}] {desc}",
            risk_level=risk,
            side_effect=side_effect,
            params_hint=json.dumps(schema.get("properties", {}), ensure_ascii=False)[:600],
            handler=handler,
        )

    @staticmethod
    def _looks_read_only(name: str) -> bool:
        n = name.lower()
        return n.startswith(_READ_NAME_PREFIXES)

    def _call_tool(self, mcp_name: str, params: Dict[str, Any]) -> ToolResult:
        try:
            self._initialize()
            result = self._rpc("tools/call", {"name": mcp_name, "arguments": params or {}}) or {}
        except Exception as e:
            return ToolResult(ok=False, observation=f"MCP {self.name}/{mcp_name} 调用失败：{e}",
                             data={"mcp": self.name, "tool": mcp_name, "error": str(e)})
        is_error = bool(result.get("isError"))
        text = self._extract_text(result.get("content", []))
        return ToolResult(
            ok=not is_error,
            observation=text or f"（MCP {self.name}/{mcp_name} 无文本返回）",
            data={"mcp": self.name, "tool": mcp_name,
                  "structured": result.get("structuredContent"),
                  "raw_content": result.get("content")},
        )

    @staticmethod
    def _extract_text(content: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for block in content or []:
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(p for p in parts if p).strip()
