# SmartUA 外部系统连接器设计文档（v3）

> **版本说明**：本文档为 v3，基于 SmartUA **v1.8.x（2026-07-22）** 的实际代码重写。
> v2（`CONNECTOR_DESIGN_v2.md`）交付的是"MockMediaConnector 有状态因果模拟 + 通用写动作
> 分发器"，v3 在其之上收敛到 **execution_mode 契约 + fail-closed live + read_state 回读**
> 三条不变量，配合 Phase 3.3 Dispatcher / Phase 4.1 三类影响 / Phase 4.2 延迟回采工作。
> v1（`CONNECTOR_DESIGN.md`）、v2 保留，作为演进对照。
>
> 文档路径：`docs/CONNECTOR_DESIGN_v3.md`

---

## 1. 三条 v3 契约

### 1.1 execution_mode 必填

`BaseConnector.execution_mode ∈ {"mock", "sandbox", "live"}`：

- 属性必须在实例化时确定，不可运行时替换。
- 所有 `pull` / `apply_action` / `read_state` 返回值都携带 `execution_mode`。
- Agent Runtime / API / SSE / 前端 **持续显示**该字段（v3 §"UI"）。

**默认值原则**：不填 → 走 mock。生产环境必须**显式**指定 live 且完成凭证配置。

### 1.2 Fail-closed live

live 模式下缺任一必要条件（凭证 / SDK / 权限 / 网络）**必须显式失败**，不允许静默回退 mock。

- `MockMediaConnector`：固定 `execution_mode="mock"`，永远不会返回 live 语义结果。
- `TikTokConnector`：真实 API 未完全实现，`resolve_credentials()` 拒绝返回 live 凭证，尝试 live 直接抛错。
- `GoogleConnector`：live 需要 SDK 已安装 + refresh_token + developer_token + login_customer_id 全部齐备；任一缺失 fail-closed。凭证解析走 `resolve_credentials()`，不再由连接器自行决定回退策略。
- `MetaConnector`：账户被封状态下（`account_status.disabled=True`）拒绝执行写动作，抛主动自治可识别的异常。

**为什么严格**：v2 曾发生"Meta 账户被封 → 静默回退 Mock 但对外报 live 成功"的错觉；v3 明确拒绝这种混淆。混淆真实/模拟就等于把系统拿去承担 v3 不承担的风险。

### 1.3 read_state 回读

`BaseConnector.read_state(entity_id) -> Dict | None`：

- 默认实现从 `current_summary()` 匹配 `campaign_id` 派生 `{status, daily_budget, roi, spend, cpi}`。
- 真实 Connector 可覆盖走原生 API（Google `campaigns.get()` / Meta `Campaign(id).api_get()`），拿到实时权威状态。
- 返回 None：表示"暂时无法回读" —— Dispatcher 停在 `unknown` 状态等 `reconcile()`，**不冒充 verified**。

Dispatcher（`agent_runtime/dispatcher.py`）在 `accepted → verified` 转移中调用 `read_state`：

- `update_campaign_status`：状态字段严格比对。
- `update_campaign_budget`：相对差 ≤ 5%（覆盖 fen/cent 取整）。
- `adjust_bid` / `rotate_creative`：`read_state` 非 None 即视为 verified（真实效果由 Phase 4 观察）。

---

## 2. Connector 抽象层布局（v3 状态）

| 文件 | 定位 | v3 变更 |
|------|------|--------|
| `base.py` | BaseConnector（`auth` / `pull` / `normalize` 抽象；通用 `apply_action` / `read_state` / `execution_mode`） | 新增 `execution_mode` 属性 + `read_state()` 默认实现 |
| `mock_media.py` | MockMediaConnector（背后 SimulationEngine 有状态因果模拟） | `execution_mode` 固定 mock；`live_summary` / `simulate_impact` / `simulate_account_disabled` 沿用 |
| `google.py` | GoogleConnector | fail-closed live；`resolve_credentials()` 缺失即抛错 |
| `meta.py` | MetaConnector | 账户被封拒绝写动作 |
| `tiktok.py` | TikTokConnector | 拒绝 live |
| `__init__.py` / `connector_service.py` | ConnectorFactory | 按 `platform + execution_mode` 组合创建 |

**关键设计**：Agent Loop 的写工具仍统一调用 `BaseConnector.apply_action(action, entity_id, **params)`。切换到真实 Meta / Google / TikTok 时上层零改动，但 execution_mode 与凭证配置必须一并到位。

---

## 3. `apply_action` 派发表（v3 不变）

```
update_campaign_status → update_campaign_status(entity_id, status)
update_campaign_budget → update_campaign_budget(entity_id, daily_budget)
update_adset_bid       → update_adset_bid(entity_id, bid_amount)
rotate_creative        → rotate_creative(entity_id)     # 仅当连接器实现
```

Agent 写工具（`_pause` / `_budget` / `_bid` / `_rotate`）通过 `ctx.connector.apply_action(...)` 派发；Dispatcher 把这次调用包装为 `media_call`，走幂等状态机（详见 `ARCHITECTURE_v3.md` §3）。

---

## 4. 延迟回采与 Connector 边界（Phase 4.2）

`impact_collector.run_due_jobs` **不直接调用 Connector**，而是从事实表读回：

- Observed 走 `FactMediaDaily`：`(app_id, source_platform, campaign_id, date)` 聚合。
- Attributed 走 `FactMMPDaily`：`(app_id, campaign_id, date)` 聚合。

Connector 只负责把媒体报表 / MMP 归因**持续入仓**（`save_dwd`）。回采时机与 Connector 的活性解耦 —— 即便 Connector 短时不可用，只要事实表已经有数据就能完成回采；反过来 Connector 拉不到数据时事实表也不会假造。

**约束**：连接器的 `pull` 结果 normalize 到 FactMediaDaily / FactMMPDaily 时必须保留 `source_platform`（`google / meta / tiktok / mock`），否则 collector 无法按 platform 过滤。`mock` 数据由 SimulationEngine 生成，`source_platform="mock"`，天然不会污染 live 回采。

---

## 5. MockMediaConnector 与因果模型（v2 沿用）

因果模型 / 演示账户 / 单例语义等在 v2 已详细描述（见 `CONNECTOR_DESIGN_v2.md` §3），v3
未变。这里补充与 v3 契约相关的要点：

- `execution_mode="mock"` 固定；`account_status`（含 `simulate_account_disabled`）供主动自治检测器识别。
- `simulate_impact(action, id, params, horizon)` 结果**仅用于 predicted envelope**（Phase 4.1），供 `tools._compute_impact` 生成 predicted metrics。**observed / attributed 永远不从 SimulationEngine 生成** —— 它们必须来自 FactMediaDaily / FactMMPDaily。
- MockMediaConnector 的写动作走同一套 dispatcher 状态机：即便 mock，也会经历 proposed → approved → dispatching → accepted → verified 全流程，保证生产 / 测试状态机一致。

---

## 6. 真实 Connector 实施状态（v3）

| 平台 | execution_mode 支持 | live 状态 | 已实现能力 | 遗留 |
|------|--------------------|-----------|-----------|------|
| Google Ads | mock / sandbox / **live** | 具备 fail-closed 路径，凭证到位即可切 | pull（Reports API） / apply_action / read_state 覆写 | 需运维配置 refresh_token + developer_token；上线前需完成 sandbox 回归 |
| Meta | mock / **live** | 依赖账户恢复；被封状态自动拒写 | pull / apply_action | Meta 恢复后切回 |
| TikTok | mock 唯一 | live **禁用** | pull（部分只读） | 真实 API 实现在 Phase 6/7 前不上线 live |
| Mock | mock 唯一 | — | 全能力（SimulationEngine 因果） | — |
| MMP (AppsFlyer) | — | live 拉取事实表 | pull 归因 → FactMMPDaily | 归因延迟窗口 D+3 内可能 completeness < 1.0 |

**切 live 检查表**：

1. `config.agent_default_platform = "google"`（或 meta）。
2. 凭证配置齐全（`GOOGLE_ADS_REFRESH_TOKEN` / `GOOGLE_ADS_DEVELOPER_TOKEN` / `GOOGLE_ADS_LOGIN_CUSTOMER_ID` 等）。
3. `BaseConnector.execution_mode = "live"` 由工厂根据凭证决定；缺凭证时工厂应抛错，绝不静默降 mock。
4. 生产环境**必须**开审批：所有 L1/L2 动作走人在环审批链。
5. 首次上线建议先 `execution_mode="sandbox"`（媒体沙盒 / 只读账户）完整跑一次 dispatch_and_verify + collector。

---

## 7. 四层数仓落库（v3 不变）

`save_ods` → `RawPayload`；`save_dwd` → `FactMediaDaily / FactMMPDaily`（幂等 `ON CONFLICT DO NOTHING`）；`ConnectorRun` 记录每次同步。`account_status` 异常由主动自治层捕获告警，不进数仓。

Phase 4.2 collector 读的就是 FactMediaDaily / FactMMPDaily —— **归一化的入仓契约是回采的地基**，任何真实连接器都必须保持这个契约的正确性。

---

## 8. 已知遗留

- 真实 Google live 未完成生产验证：具备 fail-closed 路径与 read_state 覆写，等运维凭证接入。
- Meta 依赖账户恢复：v3 期间仍以 mock 为默认。
- TikTok live 明确拒绝：Phase 6/7 门禁通过后才考虑上线。
- collector 对 D+3 之外的 MMP 数据缺失只报 `completeness=0.5` 或 `1.0`；真实完整性算法（缺日 / 缺币种 / 覆盖率）等 Phase 6 细化。

---

*文档版本：v3 | 基于 2026-07-22 SmartUA v1.8.x 实际代码 | 配套 `ARCHITECTURE_v3.md` / `API_REFERENCE_v3.md` / `LLM_ROUTING_v3.md` / `USER_MANUAL_v3.md` / `RELATED_PROJECTS_v3.md`*
