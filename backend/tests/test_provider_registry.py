"""ToolRegistry × ToolProvider 装配测试。"""
from __future__ import annotations

import pytest

from app.services.agent_runtime.providers import StaticToolProvider
from app.services.agent_runtime.tools import (
    AgentContext, Tool, ToolResult, ToolRegistry,
)


def _stub_tool(name: str, side_effect: str = "read", risk: str = "L0") -> Tool:
    def _h(params, ctx):
        return ToolResult(ok=True, observation=name, data={"called": name})
    return Tool(
        name=name, description=f"stub {name}",
        risk_level=risk, side_effect=side_effect,
        params_hint="{}", handler=_h,
    )


def test_register_provider_namespaces_tools():
    reg = ToolRegistry()
    builtin_count = len(reg.all())
    provider = StaticToolProvider("af", [_stub_tool("search"), _stub_tool("write", "write", "L3")])
    reg.register_provider(provider)

    assert reg.get("af__search") is not None
    assert reg.get("af__write") is not None
    assert reg.get("search") is None  # not exposed without prefix
    assert "af" in reg.provider_names()
    assert len(reg.all()) == builtin_count + 2


def test_unregister_provider_clears_its_tools():
    reg = ToolRegistry()
    reg.register_provider(StaticToolProvider("af", [_stub_tool("search")]))
    assert reg.get("af__search") is not None

    reg.unregister_provider("af")
    assert reg.get("af__search") is None
    assert "af" not in reg.provider_names()


def test_replacing_provider_closes_old_and_refreshes_tools():
    closed = []

    class TrackingProvider(StaticToolProvider):
        def close(self):
            closed.append(self.name)

    old = TrackingProvider("af", [_stub_tool("v1")])
    new = TrackingProvider("af", [_stub_tool("v2")])

    reg = ToolRegistry()
    reg.register_provider(old)
    assert reg.get("af__v1") is not None

    reg.register_provider(new)
    assert reg.get("af__v1") is None
    assert reg.get("af__v2") is not None
    assert closed == ["af"]


def test_provider_tools_are_callable_through_registry():
    reg = ToolRegistry()

    def _h(params, ctx):
        return ToolResult(ok=True, observation="hit", data={"p": params})

    t = Tool(name="echo", description="x", risk_level="L0",
             side_effect="read", params_hint="{}", handler=_h)
    reg.register_provider(StaticToolProvider("ext", [t]))

    fetched = reg.get("ext__echo")
    result = fetched.handler({"k": "v"}, None)
    assert result.ok is True
    assert result.data["p"] == {"k": "v"}


def test_register_tool_independent_of_providers():
    reg = ToolRegistry()
    t = _stub_tool("custom_builtin")
    reg.register_tool(t)
    assert reg.get("custom_builtin") is t
