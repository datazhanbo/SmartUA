# 2026-08-25 — P1 升级 #2：MCP Provider + Skill Loader

> 对应 `docs/HARNESS_UPGRADE_PLAN.md` 的 **#2（MCP Provider + Skill Loader，P1）**。
> 建立在 #1 Tool Pipeline Middleware 之上：外部工具和内置工具**走同一条 middleware chain**（预算护栏 / 审批 / 审计自动生效）；Skill 给已有工具提供默认参数和流程提示，**不注册新工具**。

## 背景与动机

P0 把工具管线抽成 middleware 之后，"加一个横切关注点不改 loop"已经成立。但 Agent 的工具来源仍只有 `tools.py::_build_registry()` 里硬编码的 13 个——要接第三方素材库 / 归因 / 数据看板，只能改代码；同时优化师的"经验流程"（高 ROI 才加预算、素材疲劳先 rotate 不直接提价）散落在 prompt 字符串里，无法按文件管理、无法按工具复用。

本轮交付：

- **ToolProvider SPI**：外部工具源的抽象，`ToolRegistry` 支持挂载/卸载/刷新。
- **MCPProvider**：基于 httpx 实现 MCP streamable-http JSON-RPC 最小子集，**不加 `mcp` SDK 依赖**。
- **SkillLoader**：扫描 `.md` frontmatter，把默认参数和流程文本塞进 AgentLoop。
- **两个示例 skill**：`scale_winning_campaign`（adjust_budget +20%）、`pause_fatigued_adset`（先 rotate 再 pause）。

## 新增 / 变更

### 1. Provider SPI（`agent_runtime/providers/`）

| 文件 | 职责 |
|------|------|
| `base.py` | `ToolProvider` ABC：`name` + `list_tools() -> List[Tool]` + `close()`。约定工具名必须以 `{name}__` 开头 |
| `static_provider.py` | `StaticToolProvider(name, tools)`：内存实现，测试 / 未来内置扩展用；自动加前缀 |
| `mcp_provider.py` | `MCPProvider`：streamable-http JSON-RPC 客户端 |

### 2. MCPProvider 关键设计

- 协议顺序：`initialize` → `notifications/initialized`（notification）→ `tools/list` → 每次工具调用走 `tools/call`。
- 从 initialize 响应捕获 `Mcp-Session-Id`，后续请求回带。
- 同时支持 `application/json` 与 `text/event-stream`（SSE）响应——SSE 取第一条 `data:` 行。
- **命名空间**：MCP 工具 `foo` 在本地叫 `{provider}__foo`，防止与内置工具重名。
- **安全缺省**：
  - `annotations.readOnlyHint=true` 或工具名以 `get/list/search/observe/evaluate/read/query/fetch/lookup` 开头 → `side_effect="read"` + `L0`。
  - 其它写工具默认 **L3**（仅建议，必须人审）。
  - 可经 `tool_risk` 配置显式降级，例如 `{"update_bid": "L1"}`。
- **fail-soft**：握手或 list_tools 失败时记 warning 并返回 `[]`，**AgentLoop 照常启动**——MCP server 挂了不影响内置工具。
- `refresh()` 清缓存重拉；`close()` 释放自有 httpx.Client。外部注入的 client 不 close。

### 3. ToolRegistry 扩展（`tools.py`）

```python
registry.register_provider(provider)   # 挂载；同名替换并 close 旧 provider
registry.unregister_provider("af")     # 卸载，清理该 provider 贡献的所有工具
registry.refresh_providers()           # 热刷新所有 provider
registry.provider_names()              # 已挂载 provider 名列表
```

`_refresh_providers()` 在挂载 / 刷新时按 `{name}__` 前缀先清旧工具再拉新，避免已删除的 MCP 工具残留。

### 4. SkillLoader（`agent_runtime/skills/`）

- `Skill.from_file/from_string`：用 `yaml.safe_load` 解析 frontmatter，必须有 `name`。
- 字段：`name / description / target_tool / params / when / risk_level / enabled`，正文作为执行流程。
- `SkillStore(directory)`：
  - `reload()` 扫 `*.md`，解析失败 / `enabled: false` 跳过，同名后者覆盖。
  - `for_tool(tool_name)`、`apply_params(tool_name, params)`（skill 默认 → caller 显式，后者覆盖）。
  - `effective_risk_level(tool_name, default)`（可选覆盖，AgentLoop 当前**不自动应用**，避免绕过审批护栏）。
  - `prompt_snippets()` 拼一个 markdown 块进 system prompt。
- 单例 `get_skill_store()` 读 `AGENT_SKILLS_ENABLED / AGENT_SKILLS_DIR`；`reset_skill_store()` 是测试钩子。

### 5. AgentLoop 接线（`loop.py`）

- `__init__`：装载 SkillStore、按 `settings.agent_mcp_servers` 注册 MCPProvider（**幂等**，已存在的 provider 跳过）。
- `_llm_decide`：system prompt 末尾追加 `skills.prompt_snippets()`（非空时）。
- `_dispatch`：在构造 `ToolCall` 之前，所有路径（read / L0 / L1+）统一用 `skills.apply_params(tool.name, decision.params)` 合并参数。
- loop.py 从 P0 的 437 行增至 **476 行**，仍 <500。

### 6. 配置（`config.py`）

```python
agent_mcp_enabled: bool = False
agent_mcp_servers: List[Dict[str, Any]] = []        # [{"name","url","headers","timeout","tool_risk"}]
agent_skills_enabled: bool = True
agent_skills_dir: Optional[str] = "backend/data/skills"
```

### 7. 示例 Skill（`backend/data/skills/`）

- `scale_winning_campaign.md` → `adjust_budget` 默认 `_pct=0.20`；明确"先 observe→simulate→+20%，触发 BudgetGuard 时分步加"。
- `pause_fatigued_adset.md` → `pause_adset` 触发条件；正文明确"素材疲劳优先 rotate_creative，不要对同一 AdSet 同时提议 pause 和 rotate"。

## Rationale

- **MCP vs 直接 HTTP**：MCP 正在成为工具接入的事实协议，后续可以无痛接 Claude Desktop / Cursor / 其它 server；但只用 streamable-http 最小子集，不引 SDK，避免依赖膨胀。
- **L3 缺省**：外部 server 不可信，不能因为它自报"安全"就自动写媒体账户。要降 L1/L2，必须显式配置。
- **Skill ≠ Tool**：Skill 是给 LLM 看的流程文本 + 参数默认值，**不进 registry**——这样"优化师经验"的迭代不需要改 Python，也不会让工具名爆炸。
- **命名空间前缀**：`{provider}__{tool}` 让 registry 的清理逻辑是 O(tools) 前缀匹配，不需要给每个 Tool 反向记 provider_id。

## 测试

新增三个文件，共 26 个用例：

- `tests/test_skill_loader.py`（10）：frontmatter 字段解析、prompt block、缺 frontmatter / 缺 name 报错、disabled / malformed 跳过、`apply_params` caller wins、无匹配 skill 透传、`for_tool` 过滤、risk_level 覆盖、空目录、singleton。
- `tests/test_mcp_provider.py`（11）：`httpx.MockTransport` + `FakeMCPServer` 模拟握手与 tools/list；只读判定（annotation + 名字前缀）、写默认 L3、`tool_risk` 降级、tools/call 文本往返、isError 映射、连接错误 fail-soft、HTTP 4xx 抛 `MCPError`、外部注入 client 不被 close、`refresh()` 清缓存。
- `tests/test_provider_registry.py`（5）：register 加前缀、unregister 清理、同名替换 close 旧 provider、provider 工具可通过 registry 调用、`register_tool` 不受 provider 影响。

全量：

```
cd backend && python3 -m pytest -q
# 181 passed
```

（P0 完成时 140；P1 #3 后 155；本轮 +26 → 181。）

## 已知遗留

- **无 UI 管理 skill / MCP server**：当前改 `.md` / `.env` 后需重启（或调 `refresh_providers()` / `SkillStore.reload()`）。
- **stdio / SSE transport 未支持**：MCPProvider 只实现 streamable-http。
- **BudgetGuard 字段硬编码 `daily_budget`**：若 MCP 写工具用别的字段改预算，需要后续把字段映射做成配置或加专门 middleware。
- **Skill 不参与风险分级决策**：`effective_risk_level` 暴露了但 AgentLoop 不自动应用，防止 skill 文件意外把 L2 写成 L0 绕过审批。
- **AgentLoop 的 provider 注册在 `__init__` 一次性完成**：改 `agent_mcp_servers` 后需重启；后续可加一个 `/admin/reload-providers` 接口。
