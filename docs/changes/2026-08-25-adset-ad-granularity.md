# 2026-08-25 — P1 升级 #3：AdSet/Ad 粒度 Connector + 工具

> 对应 `docs/HARNESS_UPGRADE_PLAN.md` 的 **#3（AdSet/Ad 粒度 Connector，P1）**。
> 建立在 #1 Tool Pipeline Middleware 之上：本轮新增 3 个工具、一种新写动作，**未改 `loop.py`**（仍 437 行），直接验证了 pipeline 的扩展承诺。
> 本轮只做 mock/sandbox 端到端；live 凭证下一轮接入。

## 背景与动机

升级前工具粒度只到 Campaign。`update_adset_bid` 动作虽已在 `apply_action` 里路由，但模拟引擎里把 adset_id 当 campaign_id 查 `self.campaigns`，实际改的是 `CampaignState.bid_mult`——AdSet 层是空的。模型层（`AdGroup`/`Ad`/`Creative`）和 `DimCampaignStructure` 的 adset/ad 层级早已存在，缺的是运行时的 AdSet/Ad 状态与读写工具。

## 新增 / 变更

### 1. 模拟引擎支持 AdSet/Ad 层（`simulation/engine.py`）

- 新增 `AdSetState`（id/name/campaign_id/status/bid/base_ctr/ctr_fatigue/cpi/roi/spend）与 `AdState`（id/name/adset_id/creative_id/status/creative_age/ctr/cpi/roi/spend）。
- `seed_demo_account()` 每个 campaign 自动挂 **2 个 AdSet**（一好一差：win / fatigued）+ **2 个 Ad**，确定性派生（按 id hash），可复现。
- 新增方法：`adsets_summary(campaign_id=None)`、`evaluate_creative_health(adset_id=None)`（给出 healthy/fatigued/underperforming + suggested_action）。
- `apply_action` 重构：AdSet 层动作（`update_adset_bid` / 新增 `update_adset_status`）先于 campaign 查找分派到 `_apply_adset`，**修复了原来 adset_id 被误判为 "campaign not found" 的潜在 bug**。
- `reset()` 清理 adsets/ads。

### 2. Connector 层（`connectors/base.py` + `mock_media.py`）

- `BaseConnector.apply_action` 新增 `update_adset_status` 路由：用 `getattr(self, "update_adset_status", None)`，未实现的连接器**直接返回 `success=False`（fail-closed）**，不抛 AttributeError。
- `_record_structure_change` 支持 `update_adset_status` 回写 dim_campaign_structure 的 adset 行。
- `MockMediaConnector`：新增 `update_adset_status`、`list_adsets`、`evaluate_creative`；覆盖 `read_state`——AdSet 实体返回 `{entity_level:"adset", status, bid, campaign_id, ...}`，否则回退 campaign 概览（dispatcher 回读依赖）。
- Meta/Google/TikTok 未加 adset 方法：对 `update_adset_status` 自动 fail-closed，符合"live 未实现显式拒绝"。Google 已有 `update_adset_bid` live 路径（AdGroupService），保持不变。

### 3. Dispatcher 回读（`dispatcher.py`）

- `_verify_state` 把 `update_adset_status` 纳入字段级校验：期望 `status` 与请求一致（与 campaign status 同逻辑）。`update_adset_bid` / `rotate_creative` 仍为"read_state 非空即 verified"。

### 4. 新工具（`agent_runtime/tools.py`）

| 工具 | 风险 | 副作用 | 动作 | 说明 |
|------|------|--------|------|------|
| `observe_adsets` | L0 | read | — | AdSet 层指标（出价/状态/ROI/疲劳），可按 campaign 过滤 |
| `pause_adset` | L1 | write | `update_adset_status` (PAUSED) | 广告组级止损 |
| `evaluate_creative` | L0 | read | — | Ad 层素材健康度 + 换素材建议 |
| `adjust_bid`（已有） | L2 | write | `update_adset_bid` | 本轮修正为真正作用于 AdSet.bid |

- `TOOL_TO_ACTION` 增加 `pause_adset` 映射。
- 新工具全部经既有 pipeline（BudgetGuard 在审批前生效；L0 read 直接透传；L1 提议走审批）。
- **`loop.py` 零改动**：加工具只需注册进 `_build_registry()`，这是 #1 middleware 化的直接收益。

### 5. 测试（`tests/test_adset_ad_granularity.py`，15 个）

- 引擎 seed 层级、adset 暂停/出价、非法值、未知实体、read_state 解析与 campaign 回退；
- fail-closed：未实现 `update_adset_status` 的连接器返回 `success=False`；
- 工具注册与 `TOOL_TO_ACTION` 映射、三个读/写工具的 handler；
- 端到端：`pause_adset` 经 `Dispatcher.dispatch_and_verify` + 真实 `connector.read_state` 走到 **verified**。

## 验证

- `cd backend && pytest -q`：**155 passed**（140 + 新增 15），既有断言零修改；
- `wc -l app/services/agent_runtime/loop.py`：**437 行**（新增 3 工具 + 1 动作，loop 未改）；
- mock 端 `observe_adsets` / `evaluate_creative` / `pause_adset` / `adjust_bid` 手动路径跑通。

## 已知遗留（下一轮）

- **live 凭证未接**：Meta/TikTok 的 adset 写仍是 mock 占位；Google `update_adset_bid` 有 live 路径但 `update_adset_status` 需补。按计划顺序"先 mock + 测试，再接 live"。
- **autonomy 仍绕过 pipeline**：`autonomy.py::handle_anomaly` 直调 tool.handler 的遗留与本轮无关，见 P0 变更说明。
- **AdSet/Ad 未进规则规划器**：`planner.py` 的兜底规则目前只在 campaign 层提议暂停/加预算；下一轮可让规则对低 ROI/fatigued adset 提议 `pause_adset` / `rotate_creative`。
- 前端 AdSet/Ad 视图未做；本轮交付后端能力 + mock 数据土壤。
