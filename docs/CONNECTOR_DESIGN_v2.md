# SmartUA 外部系统连接器设计文档（v2）

> **版本说明**：本文档为 v2，基于 SmartUA **v1.6.0** 重写。在保留原 `CONNECTOR_DESIGN.md`
> 连接器抽象（BaseConnector / ConnectorFactory / 四层数仓落库）的基础上，**重点新增**
> `MockMediaConnector` 有状态因果模拟引擎、通用写动作分发器 `apply_action`、以及切回真实
> Meta 的方式。v1 原版 `CONNECTOR_DESIGN.md` 保留。
>
> 文档路径：`docs/CONNECTOR_DESIGN_v2.md`

---

## 1. 前置知识（UA 数据链路，沿用 v1）

```
投放操作 → 花钱买量 → 产生花费数据 (媒体平台)
                    ↓
用户安装 → 产生行为 → 归因到具体渠道 (MMP 平台)
                    ↓
                  ROI 计算 (花了多少钱，赚了多少钱)
```

| 术语 | 大白话 | 例子 |
|------|--------|------|
| Media | 广告平台 | Meta, Google, TikTok |
| MMP | 归因平台 | AppsFlyer, Adjust |
| ODS/DWD/DWS/ADS | 原始/清洗/聚合/应用层数仓 | — |
| 幂等性 | 拉多少次结果都一样 | `source_row_hash` |
| `account_status` | 媒体账户状态 | ok / DISABLED（Meta appeal） |

---

## 2. 连接器抽象层（沿用 v1，不变）

`BaseConnector` 基类（抽象方法 `auth` / `pull` / `normalize`，通用方法 `validate` /
`_calculate_row_hash` / `save_ods` / `save_dwd` / `create_run_record` /
`update_run_success` / `update_run_failed` / `execute_pull`）保持不变。

`ConnectorFactory` 按 `platform` 名创建连接器：`"meta"` / `"google"` / `"tiktok"` / `"mock"` 等。

> ⚠️ **v2 关键设计**：Agent Loop 的写工具**不直接调用**具体连接器方法，而是统一调用
> `BaseConnector.apply_action(action, entity_id, **params)` 通用分发器（见 §4）。Meta
> 账户恢复后只需在 `config.py` 把 `agent_default_platform` 从 `"mock"` 改回 `"meta"`，
> 上层 Tool Registry 与 Agent Loop **零改动**。

---

## 3. v2 新增：`MockMediaConnector`（当前数据土壤）

### 3.1 为什么不是 v1 的随机 mock？

v1 旧 mock：每次 `pull` 重新随机、写操作只返回 `success` 不改状态 → **无因果链**。
Agent 的「动作→后续指标」之间不存在因果，记忆/反思闭环拿不到可学习样本。

v2 `MockMediaConnector`：背后是 **`SimulationEngine`（有状态因果模拟引擎）**。
- 写操作**真实修改** campaign 状态；
- `pull` 返回的「历史」会**反映这些动作的效果** → 形成 动作→指标 的因果闭环；
- 确定性响应曲线（seed 可复现），可被反思模块提取为经验。

这是 Meta 账户被封（新号直接触发 appeal）期间的**数据土壤**，使 Agentic 升级
（Phase 0~4）在真实媒体不可用前即可端到端验证。

### 3.2 模拟因果模型

每个 ACTIVE campaign 每天生成一次指标（`engine._generate_day`）：

```
spend      = budget * bid_mult（受预算上限，±噪声）
cpm        = base_cpm * bid_mult            # 出价越高单价越高
impressions= spend / cpm * 1000
ctr        = base_ctr * fatigue(age) * fresh(age)   # 素材疲劳 + 换素材短期提振
clicks     = impressions * ctr
installs   = capacity * ctr_factor * (1 - exp(-spend / k))   # 预算饱和（边际 ROI 递减）
payers     = installs * payer_rate
revenue    = payers * ltv_per_payer
roi        = revenue / spend
cpi        = spend / installs
```

**动作效果（因果可解释）**：
| 动作 | 效果 |
|------|------|
| `pause` | 次日 spend/installs/revenue=0（"止损"可被反思识别） |
| `budget +x%` | spend↑ 但 installs 次线性↑ → ROI 略降（"预算扩张边际递减"） |
| `bid +x%` | cpm↑ → cpi↑、ROI↓（"提价伤 ROI"） |
| `rotate` | age 归零，fresh 因子短期 +CTR → ROI 短期抬升后衰减（"换素材短期有效"） |

### 3.3 演示账户（`seed_demo_account`，4 个海外 UA campaign）

| campaign_id | 国家 | 日预算 | 特征 | 典型 ROI 区间 |
|-------------|------|--------|------|--------------|
| `camp_uk_001` | GB | 520 | 高 CTR / 高 LTV | 高（>1.2） |
| `camp_us_002` | US | 800 | 大预算放量 | 中高（~1.0+） |
| `camp_ca_003` | CA | 600 | 低 CTR / 低 LTV | **低（<0.7，常被止损）** |
| `camp_jp_004` | JP | 450 | 中规中矩 | 中（~0.9–1.0） |

（`advance_days(3)` 预置 3 天历史，使 `current_summary()` 立即有数据可观察。）

### 3.4 `MockMediaConnector` 接口（与 Agent/Tool Registry 对接）

| 方法 | 说明 |
|------|------|
| `pull(date_from, date_to)` | 返回区间每日指标快照（`_ensure_advanced` 自动补齐缺失日期，**幂等**） |
| `normalize(raw_rows)` | 字段标准化（与 Meta normalize 对齐，保留 roi/revenue） |
| `update_campaign_status(id, status)` | 写：暂停/恢复 |
| `update_campaign_budget(id, daily_budget)` | 写：调日预算 |
| `update_adset_bid(id, bid_amount)` | 写：调出价倍率 |
| `rotate_creative(id)` | 写：换素材（重置疲劳） |
| `account_status` | 返回媒体账户状态（主动自治据此判断被封/受限） |
| `simulate_account_disabled(bool)` | 演示用：模拟账户被封/恢复（委托给共享引擎单例） |
| `current_summary()` | **基于实时状态**的账户概览（调用 `engine.live_summary()`） |
| `simulate_impact(action, id, params, horizon)` | 包装引擎影响评估（供反思/预测用） |

> **单例要点**：`get_sim_engine()` 进程内单例，多次 pull/写共享同一份状态；
> `account_status` 委托给引擎单例，使"账户被封"状态在多次 `get_connector` 间持久
> （修复早期 per-实例丢失的 bug）。

---

## 4. v2 新增：通用写动作分发器 `apply_action`

`BaseConnector.apply_action(action, entity_id, **params)` 把 Agent 写工具的动作映射到
具体连接器方法，使 Agent 与连接器**彻底解耦**：

```python
# 支持的动作 → 连接器方法
update_campaign_status → update_campaign_status(entity_id, status)
update_campaign_budget → update_campaign_budget(entity_id, daily_budget)
update_adset_bid       → update_adset_bid(entity_id, bid_amount)
rotate_creative        → rotate_creative(entity_id)   # 仅当连接器实现该方法
```

Agent 写工具（`_pause` / `_budget` / `_bid` / `_rotate`）统一调用 `ctx.connector.apply_action(...)`，
而非具体 `connector.pause_campaign(...)`。切换到真实 Meta 时上层零改动。

---

## 5. 四层数仓落库（沿用 v1，不变）

`save_ods` → `RawPayload`（ODS 原始响应 1:1 保存）；`save_dwd` → `FactMediaDaily` /
`FactMMPDaily`（DWD，幂等 `ON CONFLICT DO NOTHING`，按 `source_row_hash`）；
`ConnectorRun` 记录每次同步（可观测）。DWS/ADS 为后续增强。

> 注：当前 `mock` 引擎的 `pull` 已能驱动 ODS/DWD 落库流程；`account_status` 异常（被封）
> 由主动自治层捕获并告警，不进入数仓写入。

---

## 6. 切换回真实 Meta（上层零改动）

```python
# backend/app/config.py
agent_default_platform: str = "meta"   # 从 "mock" 改回；Meta 账户恢复后
```

`ConnectorFactory` 在工厂把 `"mock"` 换回 `"meta"` 即可。`MockMediaConnector` 与
`MetaConnector` 实现同一套 `BaseConnector` 接口（含 `apply_action` / `current_summary` /
`simulate_impact` / `account_status` 语义），Agent Loop、Tool Registry、记忆、策略、主动自治
全部无需改动。

---

## 7. 媒体平台对接矩阵（沿用 v1，不变）

| 平台 | 类型 | 认证 | 优先级 |
|------|------|------|--------|
| Meta Ads | Media | OAuth 2.0 | P0（当前 mock 占位） |
| Google Ads | Media | OAuth 2.0 | P0 |
| TikTok Ads | Media | API Key | P0 |
| AppsFlyer | MMP | API Key | P0 |

---

## 8. 扩展能力（沿用 v1，不变）

自定义连接器插件：继承 `BaseConnector` 实现 `auth` / `pull` / `normalize` + `apply_action`，
注册进 `ConnectorFactory` 即自动可用。

---

*文档版本：v2 | 基于 2026-07-10 SmartUA v1.6.0 | 配套 `ARCHITECTURE_v2.md` / `API_REFERENCE_v2.md` / `LLM_ROUTING_v2.md` / `USER_MANUAL_v2.md` / `RELATED_PROJECTS_v2.md`*
