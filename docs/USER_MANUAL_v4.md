# SmartUA 智能投放平台 - 用户手册（v4）

> **版本说明**：本文档为 v4，基于 SmartUA **v1.9.x（2026-08-25）**。v3 面向"可托付真实预算"
> 补齐了执行模式隔离、审批过期/漂移、三档影响、学习门禁、SSE 短票据；v4 在此基础上做了一次
> **结构性重构**（工具调度抽成 Tool Pipeline Middleware）并新增一条命令起全栈：
>
> - **一条命令起全栈**：`make setup` / `make dev` / `make test` / `make db-reset`（详见 §1）。
> - **预算护栏**：写动作的日预算增幅超阈值会在审批前被拦截（详见 §4.4 与 §9）。
> - v3 的执行模式徽标、审批过期/漂移、三档影响、只学真实样本、SSE 短票据全部保留不变。
>
> v1 / v2 / v3 原版手册保留，作为演进对照。
>
> 文档路径：`docs/USER_MANUAL_v4.md`
> 配套：`ARCHITECTURE_v4.md` / `TOOL_PIPELINE_v1.md`。

---

## 目录

1. [快速开始](#1-快速开始)
2. [执行模式：真实 vs 模拟（v3 必读）](#2-执行模式真实-vs-模拟v3-必读)
3. [🤖 智能体控制台（v3 变更点）](#3-智能体控制台v3-变更点)
4. [人在环审批的新规则（v3）](#4-人在环审批的新规则v3)
5. [写动作的三档影响](#5-写动作的三档影响)
6. [策略学习门禁：Mock 永远不改规则](#6-策略学习门禁mock-永远不改规则)
7. [主动自治面板（v3 变更点）](#7-主动自治面板v3-变更点)
8. [SSE 短票据（浏览器无感）](#8-sse-短票据浏览器无感)
9. [配置对照（管理员）](#9-配置对照管理员)
10. [沿用 v2 的模块](#10-沿用-v2-的模块)
11. [常见问题（v3 增补）](#11-常见问题v3-增补)

---

## 1. 快速开始（v4：一条命令起全栈）

仓库根目录提供 `Makefile`，新环境四条命令：

```bash
make setup      # 装后端依赖 + alembic migrate + seed + 前端 npm install
make dev        # 并行起后端 :8000 + 前端 :5173（vite proxy 已配）
make test       # 后端 pytest
make db-reset   # 清库 + migrate + 重新 seed
```

- `make dev` 用 `&` 并行起前后端；Ctrl-C 后若 uvicorn 未退出，执行 `pkill -f uvicorn`，
  或用 `make dev-backend` / `make dev-frontend` 分开跑。
- 默认演示账号：管理员 `admin@smartua.com / admin123`（其余角色见 README）。
- 无 LLM 凭证时自动走规则引擎兜底，不影响体验。
- 启动前置仍是 `alembic upgrade head`（`make setup` / `make db-reset` 已包含）。

登录、选择 App、进入「智能体控制台」的流程与 v2 一致。**首次登录后建议先看页面右上角的
执行模式徽标** —— 这直接告诉你 Agent 目前是在 mock 环境练手还是在真实账户上工作。

---

## 2. 执行模式：真实 vs 模拟（v3 必读）

### 2.1 三档执行模式

| 执行模式 | 说明 | 徽标颜色 | 影响真实预算？ |
|---------|------|--------|--------------|
| **mock** | 有状态因果模拟引擎（`MockMediaConnector`） | 黄色 / 显眼 | 否 |
| **sandbox** | 媒体沙盒或只读账户（如 Google 沙盒） | 蓝色 / 谨慎 | 通常否 |
| **live** | 真实媒体账户（Google / Meta / TikTok） | 红色 / 突出 | **是** |

### 2.2 v3 的严格边界

- **Session / Step / Action / Alert 全链路**都会显示执行模式，前端持续可见。
- **切换到 live 必须显式配置**：默认永远是 mock；生产开通 live 需要运维配置凭证（refresh_token / developer_token 等）+ 显式改配置。
- **Fail-closed**：live 模式下缺凭证 / SDK / 权限 → 明确失败，绝**不**静默回退 mock 再报"成功"。TikTok 未完成真实 API 前直接拒绝 live。
- **审批卡上必显**：批准前你看得到「这次动作作用在 mock 还是 live」，避免误操作。

### 2.3 什么时候会看到 Mock

- 开发 / 演示 / 教学场景：`agent_default_platform="mock"`（默认）。
- Meta 账户被封等历史原因：仍以 mock 为兜底数据土壤（v2 传承）。
- 学习 / 复盘时提示"Mock 样本不进入策略学习"（详见 §6）。

**关键区别（vs v2）**：v2 的 mock 徽标是隐式的；v3 是持续可见 + 审批必显 + 策略不学。**混淆
真实 / 模拟在 v3 明确禁止**。

---

## 3. 🤖 智能体控制台（v3 变更点）

入口：左侧菜单「智能体控制台」→ `/agent`。

### 3.1 会话头部信息

- Session ID / 目标 / 状态 / 平台 / **执行模式徽标** / 账户 ID / 创建时间。
- 若当前为 mock，头部背景色偏黄，提示"这是模拟环境"。

### 3.2 步骤时间线

新增列 / 字段：

- 每个写动作 Step 显示：`预测影响` → `观察影响 (2h/24h/7d)` → `归因影响 (2h/24h/7d)`。
- 未回采时显式标记「未观察」/「未归因」—— **不用 0 冒充**。
- Dispatch 状态：Step 底部展示 `state: verified / unknown / failed / accepted / dispatching`；`unknown` 提示"待对账"。

### 3.3 多轮追问 / 目标续写

沿用 v2；追问文本框会显示当前 session 的 execution_mode 提示语。

---

## 4. 人在环审批的新规则（v3）

### 4.1 审批过期（Phase 3.2）

- 审批卡显示 **`expires_at`** 与倒计时。
- 过期后点批准 → 弹提示："该审批已过期（超过 X 分钟），Agent 会重新提案"。
- 系统重新提案时会说明为什么废弃旧动作（例如账户预算已变化）。

### 4.2 状态漂移检测（Phase 3.2）

- 审批批准瞬间会重读实体状态（campaign 当前 status / daily_budget / 账户状态）。
- 检测到漂移超过阈值（例如 daily_budget 变化 > 20%）→ 提示："当前预算与提案时已相差 X%，请确认后再执行" —— 并允许重新提案。

### 4.3 已批准动作走 Dispatcher

- 批准后不是直接调用媒体，而是走 **幂等状态机**：`proposed → approved → dispatching → accepted → verified`。
- 同一次批准的相同参数不会重复发媒体 API（幂等键保证）。
- 状态收敛为 `verified` 后，审批卡展示媒体侧回读结果（预算实际值 / 状态实际值），供你确认。

### 4.4 预算护栏（v4 新增）

v4 起，带 `daily_budget` 的写动作在**进入审批之前**会先过预算护栏（BudgetGuard middleware）：

- 相对增幅 `(新预算 − 当前预算) / 当前预算` 超过上限时，动作直接被拒绝，**不会生成审批卡打扰你**。
- 拒绝时 Step 会明确显示：旧预算 → 新预算、实际增幅、上限（例如"增幅 80% 超过上限 50%"）。
- 默认上限 **50%**，可经 `AGENT_BUDGET_MAX_INCREASE_PCT` 调整；冷启动（当前预算 ≤ 0 或实体缺失）不拦，避免挡住新建计划。
- read 工具、不带预算的写动作不受影响；护栏可用 `AGENT_BUDGET_GUARD_ENABLED=false` 整体关闭。

> 这是"AI 建议、人做决策"的第一道闸：明显越权的预算上调在机器侧就挡掉，只有合理范围内的调整才进入人审。

### 4.5 Skill：优化师预置流程（v4.2 新增）

Skill 是放在 `backend/data/skills/*.md` 的**小文件**，用来教 Agent "在什么场景下、用什么默认参数、按什么流程调已有工具"。它**不增加新工具**，只做两件事：

1. 给 `target_tool` 合并一组默认参数（你或模型显式给的参数优先，不会被覆盖）。
2. 把正文作为流程提示拼到 Agent 的 system prompt 里。

示例 `scale_winning_campaign.md`：

```markdown
---
name: scale_winning_campaign
target_tool: adjust_budget
params:
  _pct: 0.20
when: 用户要求"放量"且 ROI ≥ 1.5
---
1. 先 observe_campaigns 找高 ROI campaign。
2. simulate_impact 预测 +20% 的影响。
3. 调 adjust_budget，daily_budget = 当前 × 1.20。
```

完整 frontmatter 规范见 [SKILL_SYSTEM.md](SKILL_SYSTEM.md)。改完 skill 重启后端生效（或调 `get_skill_store().reload()` 热刷新）。

### 4.6 MCP Provider：接入外部工具（v4.2 新增）

Agent 可以通过 MCP (Model Context Protocol) 调用外部 server 暴露的工具。配置 `AGENT_MCP_SERVERS` 后，每个外部工具会以 `{provider}__{tool}` 的名字出现在 Agent 可用工具列表里，和内置工具一样**走预算护栏 / 审批 / 审计**。

安全缺省：

- 只读工具（MCP 标注 `readOnlyHint=true` 或工具名以 `get/list/search/observe/...` 开头）→ L0 自动执行。
- 其它写工具默认 **L3**（必须人审）；要降级在配置里显式写 `tool_risk`。
- 外部 server 连不上时记 warning 并返回空工具列表，不影响 Agent 启动。

示例：

```bash
AGENT_MCP_ENABLED=true
AGENT_MCP_SERVERS='[{"name":"af","url":"https://mcp.example.com/mcp",
  "headers":{"Authorization":"Bearer xxx"},"tool_risk":{"update_bid":"L1"}}]'
```

---

## 5. 写动作的三档影响

每个真实写动作的 Step 上会**并列展示**三个 envelope：

| 类型 | 什么时候有 | 来源 | 单位 |
|-----|-----------|------|------|
| **预测（predicted）** | 动作瞬间即有 | `simulate_impact`（模型/因果引擎） | 完整 |
| **观察（observed）** | 2h / 24h / 7d 到点回采 | 媒体报表事实表（FactMediaDaily） | 日均 |
| **归因（attributed）** | 2h / 24h / 7d 到点回采 | MMP 归因事实表（FactMMPDaily） | 日均 |

### 5.1 UI 呈现

- 三档并列，每档独立展示 `kind / metrics / window / completeness / source / freshness`。
- 未回采时显示"未观察 / 未归因" —— 明确区分「没采到」和「采到了但为零」。
- 若 `completeness < 1.0` 显示黄色提示（数据完整度不足）。

### 5.2 为什么这样区分

- **预测**只是模型对未来的估计，不能作为真实成绩。
- **观察**是媒体报表事实；**归因**是 MMP 归因事实，两者延迟 SLA 不同（观察通常 1h 内，归因可能 D+3）。
- **策略学习只用观察 + 归因**（详见 §6）。

---

## 6. 策略学习门禁：Mock 永远不改规则

**规则**：`POST /agent/strategy/learn` 只读取满足以下条件的 Episode：

- `execution_mode == "live"`
- `impact_kind ∈ {observed, attributed}`
- `completeness > 0`

### 6.1 有可用样本时

Note 前缀 `[usable=N 条真实样本]`，例如：

> `[usable=6 条真实样本] 加预算 6 次，7d 平均ΔROI<0，增幅收敛至 10%`

规则表 `rules` 更新。

### 6.2 无可用样本时（仅 Mock / 仅预测）

前端展示：

> `无可用真实样本：仅有 Mock/Sandbox 或 predicted-only Episode，策略保持不变.`

**规则不变**：`rules` 保持上一次真实学到的结果 —— **不会回归到硬编码默认**。

### 6.3 用户可见的语义

- 跑 100 个 mock 动作 → strategy.learn 不会因此改动生产规则。
- 只有 dispatcher 走完 verified、collector 完成回采、且 `execution_mode="live"` 的动作才能提权 usable，进而参与学习。
- **前端"经验复盘"（Reflector）仍读所有 Episode**（含 predicted，供人观察），但**策略参数**只被真实 usable 样本改变。

---

## 7. 主动自治面板（v3 变更点）

沿用 v2 的整体形态。v3 增量：

- Alert 卡片持续显示 `execution_mode` 徽标。
- 处置生成的动作走 dispatcher；Alert 详情"查看关联会话"跳转的 Step 上有 `dispatch.state` 字段。
- ROI 止损阈值仍优先采用已学策略；但**已学策略只由真实样本产生**，所以在 mock 环境中运行一段时间不会把阈值带偏。

**保留的 v2 承诺**：L1/L2 主动提案**永远**推给你审批；账户被封 / 花费异常**只**告警不自动缩量。

---

## 8. SSE 短票据（浏览器无感）

- 你不需要做任何事；前端会自动向 `POST /agent/sessions/{id}/stream-ticket` 申请短票据（60 秒），
  然后订阅 `/stream?ticket=...`。
- 长期 JWT 不再出现在 URL / 浏览器历史里；日志脱敏。
- 兼容开关 `agent_sse_allow_legacy_query_token` 仅供从 v2 升级过渡使用，**生产必须关闭**。

---

## 9. 配置对照（管理员）

| 配置项 | 默认 | 说明 |
|-------|------|------|
| `agent_default_platform` | `mock` | 生产必须显式改为 live 平台名，且完成对应凭证配置 |
| `agent_autonomy_enabled` | `false` | 主动巡检调度开关 |
| `agent_autonomy_interval_seconds` | `120` | 演示默认；生产建议 ≥ 300 |
| `agent_action_approval_ttl_seconds` | 建议 `600` | 审批过期窗口（Phase 3.2） |
| `agent_state_drift_pct_threshold` | 建议 `0.20` | 状态漂移阈值 |
| `agent_impact_collector_run_interval_seconds` | 建议 `300` | 外部调度器调用 `run_due_jobs` 间隔 |
| `agent_sse_short_ticket_ttl_seconds` | `60` | SSE 短票据有效期 |
| `agent_sse_allow_legacy_query_token` | `false` | 生产必须关闭 |
| `agent_budget_guard_enabled` | `true` | 预算护栏总开关（v4） |
| `agent_budget_max_increase_pct` | `0.50` | 单日预算增幅上限（相对值，0.50 = 50%，v4） |
| `agent_mcp_enabled` | `false` | 是否启用 MCP 外部工具源（v4.2） |
| `agent_mcp_servers` | `[]` | MCP server 列表 JSON：`name/url/headers/timeout/tool_risk`（v4.2） |
| `agent_skills_enabled` | `true` | 是否加载 `data/skills/*.md`（v4.2） |
| `agent_skills_dir` | `backend/data/skills` | skill 目录（v4.2） |
| `agent_strategy_path` | `backend/data/strategy.json` | 策略落盘路径 |

启动前置：`alembic upgrade head` —— v3 起 schema 由 Alembic 管理，`create_all()` 仅保留在测试路径。

---

## 10. 沿用 v2 的模块

以下模块 v3 未变，详见 `USER_MANUAL_v2.md`：

- 快速开始 / 平台概览 / 角色与权限
- ROI360 数据分析
- Campaign 健康监控
- 四层运营实体模型
- 素材管理
- 意图驱动操作（单轮遗留）
- 操作安全分级 L0–L3（Agent 与意图共用）
- 策略模板
- 智能体控制台基础形态（对话 / 步骤 / 智能体大脑 Tabs）

---

## 11. 常见问题（v3 增补）

### Q: 我怎么知道 Agent 是不是在真实账户上跑？
A: 看会话头部 / 步骤 / 审批卡的执行模式徽标。**Mock = 黄色，Sandbox = 蓝色，Live = 红色**。
v3 承诺：三档执行模式永远持续可见，不会静默切换。

### Q: 我批准了一个动作，但 5 分钟后再点批准提示"已过期"？
A: 这是 Phase 3.2 的审批过期机制。审批窗口默认 10 分钟，超时后账户状态可能已变化，Agent 会
重新提案（并说明差异），避免执行陈旧决策。

### Q: 我跑了半天 mock，为什么 strategy.learn 说"策略保持不变"？
A: 这是 Phase 4.3 的学习门禁：**Mock / predicted-only 样本永远不会改动生产规则**。要产生
可学习样本，需要：live 执行 + 回采到真实 media / MMP 数据 + `completeness>0`。这是"永不
用 Mock 冒充 live"承诺的一部分。

### Q: 三档影响（预测/观察/归因）什么时候能全部到齐？
A: 预测立即有；观察通常 1 小时内到（媒体报表）；归因视 MMP 延迟，通常 D+1 到 D+3。前端会
显式标记"未观察 / 未归因"，禁止用 0 冒充。

### Q: 我看不到旧的 `?token=` SSE 链接了？
A: v3 起 SSE 使用短票据。前端会自动申请并订阅；旧链接（长期 JWT 明文暴露）已默认关闭。

### Q: v3 支持真实媒体投放吗？
A: 结构上支持（Google fail-closed live 路径已就绪、Dispatcher 状态机已就绪、回采与门禁已就绪），
但**当前默认仍是 mock**。切 live 需运维完成凭证配置 + 显式改 `agent_default_platform`。
TikTok live 直到真实 API 上线前明确禁止。

---

*文档版本：v4 | 基于 2026-08-25 SmartUA v1.9.x 实际代码 | 配套 `ARCHITECTURE_v4.md` / `TOOL_PIPELINE_v1.md` / `API_REFERENCE_v3.md` / `CONNECTOR_DESIGN_v3.md` / `LLM_ROUTING_v3.md` / `RELATED_PROJECTS_v3.md`*
