"""MCPProvider 单测：用 httpx.MockTransport 模拟 streamable-http server。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from app.services.agent_runtime.providers.mcp_provider import (
    MCPError, MCPProvider,
)


# ---------- Mock server ------------------------------------------------------- #

class FakeMCPServer:
    """最小 MCP streamable-http 假服务器：处理 initialize / tools/list / tools/call。"""

    def __init__(self, tools: List[Dict[str, Any]], *,
                 call_response: Any = None,
                 reject_call: bool = False):
        self.tools = tools
        self.call_response = call_response
        self.reject_call = reject_call
        self.calls: List[Dict[str, Any]] = []
        self.initialized_notifications = 0
        self.session_id = "sess-123"

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        method = body.get("method")
        params = body.get("params") or {}
        is_notification = "id" not in body
        self.calls.append(body)

        if method == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": self.session_id,
                         "Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": body["id"],
                      "result": {"protocolVersion": "2025-06-18",
                                 "capabilities": {"tools": {}},
                                 "serverInfo": {"name": "fake", "version": "0.1"}}},
            )
        if method == "notifications/initialized" and is_notification:
            self.initialized_notifications += 1
            return httpx.Response(202, json=None)
        if method == "tools/list":
            return httpx.Response(
                200, headers={"Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": body["id"],
                      "result": {"tools": self.tools}},
            )
        if method == "tools/call":
            if self.reject_call:
                return httpx.Response(
                    200, headers={"Content-Type": "application/json"},
                    json={"jsonrpc": "2.0", "id": body["id"],
                          "result": {"isError": True,
                                     "content": [{"type": "text",
                                                  "text": "boom: invalid arg"}]}},
                )
            return httpx.Response(
                200, headers={"Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": body["id"],
                      "result": self.call_response
                      or {"content": [{"type": "text",
                                       "text": f"called {params.get('name')}"}]}},
            )
        return httpx.Response(404, json={"jsonrpc": "2.0", "id": body.get("id"),
                                         "error": {"code": -32601, "message": "method not found"}})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


TOOL_SPECS = [
    {"name": "search_creative",
     "description": "搜索素材库",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "update_bid",
     "description": "改出价（写）",
     "inputSchema": {"type": "object", "properties": {"bid": {"type": "number"}}}},
    {"name": "list_campaigns",
     "description": "list 前缀判定只读",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _provider(server: FakeMCPServer, **kw) -> MCPProvider:
    return MCPProvider("af", "http://fake/mcp", client=server.client(), **kw)


def test_initialize_handshake_and_list_tools():
    server = FakeMCPServer(TOOL_SPECS)
    p = _provider(server)
    tools = p.list_tools()

    names = sorted(t.name for t in tools)
    assert "af__search_creative" in names
    assert "af__update_bid" in names
    assert "af__list_campaigns" in names

    methods = [c.get("method") for c in server.calls]
    assert methods[0] == "initialize"
    assert methods[1] == "notifications/initialized"
    assert methods[2] == "tools/list"
    assert server.initialized_notifications == 1


def test_readonly_detection_from_annotation_and_prefix():
    server = FakeMCPServer(TOOL_SPECS)
    p = _provider(server)
    tools = {t.name: t for t in p.list_tools()}

    assert tools["af__search_creative"].side_effect == "read"
    assert tools["af__search_creative"].risk_level == "L0"

    assert tools["af__list_campaigns"].side_effect == "read"
    assert tools["af__list_campaigns"].risk_level == "L0"

    assert tools["af__update_bid"].side_effect == "write"
    assert tools["af__update_bid"].risk_level == "L3"


def test_tool_risk_config_downgrades_write_to_l1():
    server = FakeMCPServer(TOOL_SPECS)
    p = _provider(server, tool_risk={"update_bid": "L1"})
    tools = {t.name: t for t in p.list_tools()}
    assert tools["af__update_bid"].risk_level == "L1"


def test_tools_call_round_trip_returns_text():
    server = FakeMCPServer(
        TOOL_SPECS,
        call_response={"content": [
            {"type": "text", "text": "result line 1"},
            {"type": "text", "text": "result line 2"},
        ]},
    )
    p = _provider(server)
    tool = {t.name: t for t in p.list_tools()}["af__search_creative"]
    res = tool.handler({"q": "ai video"}, None)

    assert res.ok is True
    assert "result line 1" in res.observation
    assert res.data["mcp"] == "af"
    assert res.data["tool"] == "search_creative"

    call_body = next(c for c in server.calls if c.get("method") == "tools/call")
    assert call_body["params"]["name"] == "search_creative"
    assert call_body["params"]["arguments"] == {"q": "ai video"}


def test_tools_call_iserror_maps_to_failed_result():
    server = FakeMCPServer(TOOL_SPECS, reject_call=True)
    p = _provider(server)
    tool = {t.name: t for t in p.list_tools()}["af__update_bid"]
    res = tool.handler({"bid": 1.0}, None)
    assert res.ok is False
    assert "boom" in res.observation


def test_list_tools_failsoft_on_connection_error():
    def boom(request):
        raise httpx.ConnectError("nope", request=request)

    p = MCPProvider("af", "http://fake/mcp",
                    client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert p.list_tools() == []
    # second call still returns [] (not raising)
    assert p.list_tools() == []


def test_http_4xx_raises_mcperror_on_rpc_directly():
    def not_authorized(request):
        return httpx.Response(401, json={"jsonrpc": "2.0",
                                         "error": {"code": -32001,
                                                   "message": "unauthorized"}})

    p = MCPProvider("af", "http://fake/mcp",
                    client=httpx.Client(transport=httpx.MockTransport(not_authorized)))
    with pytest.raises(MCPError):
        p._initialize()


def test_close_owned_client():
    server = FakeMCPServer(TOOL_SPECS)
    client = server.client()
    p = MCPProvider("af", "http://fake/mcp", client=client)
    p.list_tools()
    p.close()
    # client provided externally is NOT closed by provider (owns_client=False)
    assert not client.is_closed


def test_refresh_clears_cache():
    server = FakeMCPServer(TOOL_SPECS)
    p = _provider(server)
    first = p.list_tools()
    assert len(first) == 3
    # mutate server tool list; cached list still returned
    server.tools.append({"name": "new_one", "inputSchema": {"properties": {}}})
    assert len(p.list_tools()) == 3
    # refresh re-fetches
    refreshed = p.refresh()
    assert any(t.name == "af__new_one" for t in refreshed)
