# SmartUA 相关开源项目参考（v2）

> **版本说明**：本文档为 v2，基于 SmartUA **v1.6.0** 重写。保留原 `RELATED_PROJECTS.md`
> 的广告投放/归因/数据管道参考，**新增** Agentic / 自治 / 多智能体框架与强化学习出价方向，
> 与 SmartUA 的 Agent Loop（Phase 1）、记忆/策略（Phase 2–3）、主动自治（Phase 4）直接对应。
> v1 原版 `RELATED_PROJECTS.md` 保留。
>
> 文档路径：`docs/RELATED_PROJECTS_v2.md`

---

## 🤖 AI Agent / 多智能体框架（与 Agent Loop 最相关）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **LangGraph** | ⭐ 8k+ | https://github.com/langchain-ai/langgraph | 把 Agent 编排成**有状态图**（节点=步骤，边=转移），天然支持人在环（interrupt）、记忆、多轮 | ★★★★★ |
| **AutoGen** | ⭐ 30k+ | https://github.com/microsoft/autogen | 微软多智能体对话框架，可定义 Agent 协作/辩论/代码执行 | ★★★★☆ |
| **CrewAI** | ⭐ 20k+ | https://github.com/crewAIInc/crewAI | 角色化多智能体（角色/任务/流程），适合把"优化师/分析/审批"拆成 Crew | ★★★★☆ |
| **CAMEL** | ⭐ 9k+ | https://github.com/camel-ai/camel | 早期多智能体角色扮演与协作研究框架 | ★★★☆☆ |
| **LlamaIndex Agents** | ⭐ 35k+ | https://github.com/run-llama/llama_index | 以"数据/检索"为中心的 Agent 与工具编排 | ★★★☆☆ |
| **AutoGPT / AgentGPT** | ⭐ 160k+ | https://github.com/Significant-Gravitas/AutoGPT | 目标驱动自主 Agent 的早期代表（"给目标，它自己干"） | ★★★☆☆ |
| **DSPy** | ⭐ 17k+ | https://github.com/stanfordnlp/dspy | 把 LLM 提示词/管线"编程化"+ 自动优化（对应 Phase 3 的"策略/提示词自演化"方向） | ★★★★☆ |

> **可借鉴点**：SmartUA 的 `AgentLoop` ReAct 循环 + `AgentSession`（多轮/审批/上下文）+
> `AutonomyStore`（告警流）与 LangGraph 的「有状态图 + interrupt 人在环」高度同构；
> Phase 3 的策略自演化与 DSPy 的"提示词/参数自优化"思路一致。

---

## 🛡️ 自治 / 调度 / 监控（与 Phase 4 主动自治相关）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **APScheduler** | ⭐ 9k+ | https://github.com/agronholm/apscheduler | Python 后台定时/间隔调度（SmartUA 主动巡检即用它 `BackgroundScheduler`） | ★★★★★ |
| **Prefect** | ⭐ 17k+ | https://github.com/PrefectHQ/prefect | 工作流编排 + 调度 + 观测，适合把"巡检→处置→复盘"做成可观测流水线 | ★★★★☆ |
| **Airflow** | ⭐ 32k+ | https://github.com/apache/airflow | 数据管道编排（原 RELATED 已列，亦可用于巡检 DAG） | ★★★★☆ |
| **Healthchecks.io / 监控告警** | — | https://github.com/healthchecks/healthchecks | 周期任务心跳 + 异常告警（对应主动自治"账户被封主动告警"） | ★★★☆☆ |

> **可借鉴点**：SmartUA `AutonomyEngine.scan()` + `AnomalyDetector` + APScheduler 的组合，
> 可进一步接入 Prefect 做"每次巡检一个可观测 run"、接入外部告警通道（企微/飞书/邮件）做异动推送。

---

## 📈 强化学习 / 出价优化（与策略自演化方向相关）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **Ray RLlib** | ⭐ 22k+ | https://github.com/ray-project/ray | 工业级 RL 库，可做"出价/预算"策略的在线学习 | ★★★★☆ |
| **Stable-Baselines3** | ⭐ 9k+ | https://github.com/DLR-RM/stable-baselines3 | 轻量 RL 实现，适合做预算分配 MDP 原型 | ★★★☆☆ |
| **Prophet** | ⭐ 16k+ | https://github.com/facebook/prophet | 时间序列预测（预测 CPI/ROI 趋势，供 Agent 决策） | ★★★★☆ |
| **Gymnasium** | ⭐ 11k+ | https://github.com/Farama-Foundation/Gymnasium | RL 环境标准接口（可把 `SimulationEngine` 包装成 Gym 环境做 RL 训练） | ★★★☆☆ |

> **可借鉴点**：当前 SmartUA 的策略为「规则挖掘 + 标量阈值学习」（解释性强、零训练成本）。
> 后续若要做"出价/预算在线优化"，可把 `SimulationEngine` 包成 Gym 环境，用 RLlib 训练策略，
> 再由 `StrategyStore` 接管为可迁移参数。

---

## 🎯 广告投放 & 营销归因（沿用 v1）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **GrowthBook** | ⭐ 5.2k | https://github.com/growthbook/growthbook | 开源 A/B 测试和特征标记 + 归因 + ROI 追踪 | ★★★★★ |
| **AdServe** | ⭐ 1.2k | https://github.com/adsumo/adserve | 开源广告服务器 | ★★★★☆ |
| **Revive Adserver** | ⭐ 1.5k | https://github.com/revive-adserver/revive-adserver | 广告管理系统 | ★★★☆☆ |

---

## 📊 数据分析 & 归因（沿用 v1）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **Matomo** | ⭐ 18.5k | https://github.com/matomo-org/matomo | 开源分析替代 | ★★★★★ |
| **PostHog** | ⭐ 14k | https://github.com/PostHog/posthog | 事件驱动分析 + 会话重放 | ★★★★☆ |
| **ChannelAttribution** | ⭐ 400 | https://github.com/gtesei/ChannelAttribution | 归因分析 | ★★★☆☆ |

---

## 🔄 数据管道 & 工作流（沿用 v1）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **Apache Airflow** | ⭐ 32k+ | https://github.com/apache/airflow | 数据管道编排 | ★★★★★ |
| **Dagster** | ⭐ 8.5k | https://github.com/dagster-io/dagster | 数据编排/ETL | ★★★☆☆ |
| **dbt** | ⭐ 7.8k | https://github.com/dbt-labs/dbt-core | 数仓转换 | ★★★★☆ |

---

## 💾 客户数据平台（沿用 v1）

| 项目 | Stars | 地址 | 简介 | 相关度 |
|------|-------|------|------|--------|
| **RudderStack** | ⭐ 4.8k | https://github.com/rudderlabs/rudder-server | 开源 CDP | ★★★★☆ |
| **PostHog** | ⭐ 14k | https://github.com/PostHog/posthog | 产品分析 | ★★★★☆ |

---

## 🧠 与 SmartUA 的对照总结

| SmartUA 能力（Phase） | 对应开源范式 | 当前实现 |
|----------------------|-------------|---------|
| Agent Loop 规划+多轮+人在环（P1） | LangGraph 有状态图 + interrupt | `AgentLoop` + `AgentSession` + `AgentStep` |
| 记忆/反思（P2） | LLM Memory / Experience Replay | `EpisodicMemory` + `Reflector` |
| 策略自演化（P3） | DSPy 自优化 / RL 策略 | `StrategyStore`（标量阈值 + 落盘） |
| 主动自治（P4） | APScheduler + 监控告警 | `AutonomyEngine` + `AnomalyDetector` + APScheduler |
| 数据土壤（P0） | 模拟环境 / Gym | `SimulationEngine`（有状态因果） |

---

*文档版本：v2 | 基于 2026-07-10 SmartUA v1.6.0 | 配套 `ARCHITECTURE_v2.md` / `API_REFERENCE_v2.md` / `CONNECTOR_DESIGN_v2.md` / `LLM_ROUTING_v2.md` / `USER_MANUAL_v2.md`*
