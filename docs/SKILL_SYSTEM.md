# Skill & MCP Provider 手册（v4.2 / 2026-08-25）

P1 #2 给 Agent Loop 接了两个"外部能力源"：

- **Skill**：`.md` 形式的优化师预置流程，给已有工具提供默认参数 + 一段给 LLM 的流程提示。**不注册新工具**。
- **MCP Provider**：通过 MCP (Model Context Protocol) streamable-http 协议把外部 server 的工具拉进 ToolRegistry。**注册的是真工具**，走同一套 middleware / 审批 / 预算护栏。

本文是这两个机制的参考手册。设计原则见 `docs/HARNESS_UPGRADE_PLAN.md` P1 #2。

---

## 1. Skill 系统

### 1.1 Skill 的边界

- Skill **不是工具**，不进 `ToolRegistry`，不增加 LLM 可 `action` 的名字。
- Skill 只做两件事：
  1. 给 `target_tool` 提供一组**默认参数**（`params`），用户/模型显式给的参数优先。
  2. 把一段 Markdown 流程文本塞进 LLM 的 system prompt，指导"什么时候调、怎么调"。
- Skill 可以覆盖 `target_tool` 的 `risk_level`（一般不建议；让审批护栏以工具事实源为准）。

### 1.2 Frontmatter 字段

文件位置：`backend/data/skills/*.md`（由 `AGENT_SKILLS_DIR` 配置）。

```markdown
---
name: scale_winning_campaign           # 必填，唯一
description: 给高 ROI campaign 小幅加预算  # 一句话，进 system prompt
target_tool: adjust_budget            # 必填，作用的工具名
params:                               # 可选，默认参数（LLM 显式参数优先）
  _pct: 0.20
when: ROI ≥ 1.5 且状态 ACTIVE          # 可选，自然语言触发条件
risk_level: L1                        # 可选，覆盖工具默认风险（不建议）
enabled: true                         # 可选，默认 true
---

执行流程：

1. 先 observe_campaigns。
2. simulate_impact 预测 +20%。
3. adjust_budget，daily_budget = 当前 × 1.20。
```

加载器：`app/services/agent_runtime/skills/loader.py::SkillStore`。

- 目录扫描发生在 `get_skill_store()` 首次调用（AgentLoop 启动时）。
- 解析失败（YAML 语法错、缺 `name`、缺 frontmatter）的文件记 warning 并跳过，不阻塞启动。
- `enabled: false` 的文件不加载。
- 同名 skill 后者覆盖（记 warning）。

### 1.3 运行时如何生效

`AgentLoop._dispatch` 在构造 `ToolCall` 之前：

```python
params = self.skills.apply_params(tool.name, decision.params)
```

合并顺序：**skill 默认参数 → LLM/用户显式参数**（后者覆盖前者）。

`AgentLoop._llm_decide` 在 system prompt 末尾追加：

```
【可用 Skill（优化师预置流程与默认参数）】
### Skill: scale_winning_campaign（作用于工具 `adjust_budget`）
...
```

Skill 之间相互独立；多个 skill 作用于同一 tool 时，按 `for_tool()` 返回顺序合并 params（默认无强顺序保证，不要在不同 skill 里给同一参数设不同默认值）。

### 1.4 加一个新 Skill

1. 在 `backend/data/skills/` 新建 `<name>.md`，按上面 frontmatter 模板写。
2. 重启后端（当前无热加载；若需热更新，调 `get_skill_store().reload()`）。
3. 写一个单元测试到 `tests/test_skill_loader.py` 或用一条 Agent 目标走通流程。

### 1.5 配置

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `AGENT_SKILLS_ENABLED` | `true` | 关掉则不加载任何 skill |
| `AGENT_SKILLS_DIR` | `backend/data/skills` | skill 目录绝对路径 |

---

## 2. MCP Provider

### 2.1 工具命名空间与安全缺省

每个 MCP server 对应一个 `MCPProvider(name=...)`。该 server 暴露的工具 `foo` 在本地叫：

```
{provider_name}__foo
```

比如 `name="af"` server 的 `search_creative` → `af__search_creative`。LLM 必须用这个全名去调。

风险分级缺省（可在配置里覆盖）：

| 信号 | side_effect | risk_level |
|------|-------------|-----------|
| MCP `annotations.readOnlyHint=true` | read | L0（自动） |
| 工具名以 `get/list/search/observe/evaluate/read/query/fetch/lookup` 开头 | read | L0 |
| 其它 | write | **L3**（仅建议，必须人审） |

外部 server 来的写动作**默认 L3** 是有意的：MCP server 可能是第三方，不能因为它自报"安全"就自动写媒体账户。要降级，显式在配置里指定 `tool_risk`。

### 2.2 协议实现

`app/services/agent_runtime/providers/mcp_provider.py`：

- 基于 `httpx`，**不引入 `mcp` SDK**——当前只需 streamable-http JSON-RPC 最小子集。
- 握手顺序：`initialize` → `notifications/initialized`（notification）→ `tools/list`。
- 从 initialize 响应里捕获 `Mcp-Session-Id` header，后续请求带上。
- 响应可能是 `application/json` 或 `text/event-stream`（SSE）；SSE 时取第一条 `data:` 行解析。
- 工具调用：`tools/call {name, arguments}`，从 `content[].text` 拼 observation；`isError=true` 映射成 `ToolResult(ok=False)`。
- 连接失败 / 握手失败：`list_tools()` 返回 `[]` + warning，**不阻塞 AgentLoop 启动**（fail-soft）。
- 每次调用都走同一个 `httpx.Client`（连接复用），进程关闭时 `close()`。

### 2.3 配置

```python
# 在 .env 或 settings：
AGENT_MCP_ENABLED=true
AGENT_MCP_SERVERS='[
  {
    "name": "af",
    "url": "https://mcp.example.com/mcp",
    "headers": {"Authorization": "Bearer xxx"},
    "timeout": 15.0,
    "tool_risk": {"update_bid": "L1"}
  }
]'
```

字段：

- `name`：provider 名，用作工具命名空间前缀，**全局唯一**。
- `url`：MCP streamable-http endpoint。
- `headers`：可选，附加到每个 JSON-RPC 请求（鉴权 token 等）。
- `timeout`：秒，默认 15。
- `tool_risk`：可选，`{mcp_tool_name: "L0|L1|L2|L3"}`，覆盖默认 L3 写 / L0 读。

AgentLoop 启动时调 `_register_configured_providers()`，**幂等**：同名 provider 已注册则跳过。

### 2.4 加一个新 MCP Server

1. 拿到 server URL 和鉴权 header。
2. 在配置里加一条 `agent_mcp_servers`。
3. 重启后端；看启动日志确认没有 `列出工具失败` warning。
4. 在一次 Agent 会话里让它调 `<name>__<tool>`，或直接 `ToolRegistry.get("<name>__<tool>")` 验证。

热刷新（不重启）：

```python
from app.services.agent_runtime.tools import get_tool_registry
get_tool_registry().refresh_providers()
```

### 2.5 与 Tool Pipeline 的关系

MCP 工具和内置工具**走同一条 middleware chain**：

- 读工具自动放行（L0）。
- 写工具过 `BudgetGuard`（但 BudgetGuard 只识别 `daily_budget` 字段；MCP 工具若没有该字段，直接放行）。
- L1/L2/L3 写工具生成 APPROVAL step，人在环。
- 执行结果落 `AgentStep`、`ActionLog`、Episode（如有 DB）。

这意味着给 MCP 工具加预算护栏、审计、PII 拦截，不需要改 MCPProvider 本身——加 middleware 即可（见 `docs/TOOL_PIPELINE_v1.md`）。

### 2.6 写自定义 Provider

继承 `app.services.agent_runtime.providers.base.ToolProvider`：

```python
class MyProvider(ToolProvider):
    name = "my"

    def list_tools(self) -> list[Tool]:
        return [Tool(name="my__hello", ..., handler=self._hello)]

    def close(self):
        ...

    def _hello(self, params, ctx):
        return ToolResult(ok=True, observation="hi", data={})
```

**契约**：所有 `Tool.name` 必须以 `{self.name}__` 开头，否则 registry refresh 时会漏清。`StaticToolProvider` 已自动加前缀，可作测试参考。

注册：

```python
get_tool_registry().register_provider(MyProvider())
```

---

## 3. 测试

- `tests/test_skill_loader.py`：frontmatter 解析、params 合并（caller wins）、disabled / malformed 跳过、prompt 片段、singleton。
- `tests/test_mcp_provider.py`：用 `httpx.MockTransport` + `FakeMCPServer` 模拟 initialize/tools/list/tools/call；覆盖只读判定、L3 缺省、tool_risk 降级、isError、4xx 抛错、连接失败 fail-soft、refresh、client 生命周期。
- `tests/test_provider_registry.py`：register/unregister/replace（close 旧 provider）、命名空间隔离、provider 工具可通过 registry 调用。

完整验收：`cd backend && python3 -m pytest -q`（181 passed，2026-08-25）。

---

## 4. 已知边界

- Skill 没有 UI / 数据库版本管理——当前是"文件系统 + 重启生效"。
- MCP 只实现 streamable-http；stdio、SSE transport、resources/prompts 能力暂未支持。
- MCP 工具没有自动 schema 校验；`params_hint` 只截 600 字进 system prompt，错误参数由 server 返回 isError。
- BudgetGuard 只对 `daily_budget` 字段生效；若 MCP 写工具用别的字段名改预算，需要后续加配置化字段映射或专门 middleware。
