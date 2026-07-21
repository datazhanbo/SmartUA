# SmartUA 下一阶段迭代路线图（统一版）

> 合并两份输入：
> 1. 用户上轮定的三大重点 —— ① 工具/MCP/CLI/API 供给 ② 复盘学策略 ③ 投放知识库
> 2. GPT-5.6 的《SmartUA 项目分析与改进建议》（市场对标 + 数据地基 + 进阶路线）
>
> 状态：执行中（Phase A 已完成 ✅，Phase B/C/D 待启动）。
> 当前版本：v1.8.0（Phase A 真实数据地基：持久化 + 真实渠道 + 真实归因接地）+ v1.7.0（Ark 推理 + SSE 流式 + 外部检索 + abort/redirect）。

---

## 0. 核心判断（先讲结论）

GPT 文档点出了最关键的一句话：**SmartUA 最大的瓶颈不是架构，而是"真实数据土壤"缺失**——没有真实渠道、没有真实归因，Agent 再聪明也只是在沙盘里打仗。

而用户上轮定的三支柱（工具/复盘/知识库）是**智能深度**，解决"Agent 有多聪明"。

两者不是二选一，而是**地基 → 智能 → 领先**的递进关系：

```
Phase A 真实数据地基  ──▶  Phase B 能力供给  ──▶  Phase C 复盘+知识+市场差距  ──▶  Phase D 领先市场
(持久化/渠道/归因)        (工具/MCP/粒度/跨渠道)     (策略学习/知识库/A-B/推送)        (RL/多Agent/A2A)
```

- 没有 A，B/C 是"聪明但瞎"；
- 没有 B/C，A 只是把数据接进来却不会用；
- D 是锦上添花，等前三层稳了再做。

---

## 1. 当前真实状态核对（代码实证，修正 GPT 文档的过时处）

| 项 | GPT 文档(基线 v1.6) 说法 | 代码实测(v1.8) | 结论 |
|---|---|---|---|
| LLM 大脑 | "支持但依赖规则降级" | `ArkProvider` 已真实接入方舟推理模型，`reasoning_tokens>4000` | ✅ 已解决，非降级 |
| 会话/记忆持久化 | "进程内单例，重启即失" | v1.8 `session/memory/autonomy` 三 store 双轨 SQLite 持久化 | ✅ 已解决（A1） |
| 策略持久化 | 归在"重启即失" | `strategy.py:157` 已 `json.dump` 到 `agent_strategy_path` | ✅ 已解决（Phase 3） |
| 真实渠道 | "仅 Mock 单渠道" | v1.8 `TikTokConnector` 实现+注册；Meta/Google 抽象就绪，缺凭证走 Mock | ⚠️ A2 代码就绪，真实接通待凭证 |
| 真实归因 | "无" | v1.8 `current_summary` 从 FactMediaDaily 聚合、roi 取 FactMMPDaily（无则 None） | ⚠️ A3 接地完成，真实 MMP 拉取待密钥 |
| 粒度 | "仅 Campaign" | 工具仅到 Campaign 层 | ❌ 仍为真缺口（B5 待做） |
| 外部检索 | （未提） | `market_research` 真实搜索+MCP 框架已就绪 | ✅ 已部分具备 |

→ GPT 文档的 🔴 三项里，**持久化已解决（A1）**；**真实渠道/归因代码与护栏已备好（A2/A3），真实接通待 Meta 解封 / MMP 密钥**；策略持久化已解决（Phase 3）。

---

## 2. 统一分阶段路线图

### Phase A — 真实数据地基（对应 GPT 🔴，必须）
| 编号 | 内容 | 关键改动 | 验收 |
|---|---|---|---|
| A1 ✅ | **状态持久化（已完成）** | `AgentSession`/`AgentStep`/`EpisodicMemory`/告警流 → SQLite 表（双轨：内存缓存+SQLite WAL，`busy_timeout=5000`）；`StrategyStore` JSON 已持久，保留 | 重启后端，会话/记忆/告警不丢；可多实例 ✅ |
| A2 ✅ | **真实渠道 Connector（已完成，Mock 待命）** | `TikTokConnector` 已实现+注册；恢复 Meta（账号解封切 `config.agent_default_platform="meta"`，接口已预留）；`GoogleAdsConnector` 抽象就绪；Mock 作 fallback | 接 Google/TikTok 后 agent 在真实数据上决策 ✅ |
| A3 ✅ | **真实归因接地（已完成，真实 MMP 拉取待密钥）** | `BaseConnector.current_summary`/`account_status`/`simulate_impact` 通用实现（聚合 FactMediaDaily、roi 取 FactMMPDaily，无则 None）；真实 AppsFlyer/Adjust/Kochava 回传待密钥 | `observe` 返回真实归因指标（缺 MMP 时 roi=None 安全）✅ |

### Phase B — 能力供给（对应 GPT 🟡 工具侧 + 用户支柱①）
| 编号 | 内容 | 关键改动 | 验收 |
|---|---|---|---|
| B1 | **ToolCatalog 自动注册** | `catalog.py` 统一扫描 内置/MCP/CLI/API 四类 → 注入 `ToolRegistry`（L0–L3 风险启发式） | 工具来源可插拔 |
| B2 | **MCP 桥 + CLI 沙箱 + API 自动生成** | `MCPToolBridge` 动态注册；`shell_tool`(allowlist)；`api_tool`(OpenAPI→工具) | agent 能跑数据脚本、调外部 API |
| B3 | **关键读工具** | `creative_intel`(竞品素材)/`analytics_query`(归因 ROAS)/`trending_topics`/`store_reviews`/`data_script` | 决策前能看到市场信号 |
| B4 | **跨媒体预算分配** (GPT #4) | `allocate_budget_cross_channel`：多渠道 ROI + 总预算 → 分配建议（ROI 加权→Prophet 前瞻） | 输出跨渠道分配方案 |
| B5 | **粒度下钻** (GPT #6) | `observe_adsets`/`pause_adset`/`adjust_adset_bid`/`evaluate_creative_performance` + 素材疲劳评分 + 胜出素材识别 | Agent 能下钻 AdSet/Ad/Creative |
| B6 | **更聪明的规划** | Plan-and-Execute + Critic 校验 + 从成功 Episode 抽 few-shot | 首轮决策质量提升 |

### Phase C — 复盘学策略 + 知识库 + 市场差距（用户支柱②③ + GPT 🟡 策略侧）
| 编号 | 内容 | 关键改动 | 验收 |
|---|---|---|---|
| C1 | **Reflector 因果归因** (支柱②) | 复盘产出 动作→指标 delta + 可学习参数候选 | 复盘不再是纯摘要 |
| C2 | **StrategyStore 扩维 + 治理** (支柱②) | 参数 3→~13；贝叶斯/反事实仿真/跨账户迁移；策略 diff UI + L2 人审 + 版本回滚 + 夜间批学习 | 多账户 20+ Episode 参数收敛可解释 |
| C3 | **策略 A/B 闭环** (GPT #7) | `StrategyABTest`：新旧策略各 20% 流量 3 天，统计显著性后推全 | 策略迭代有显著性保障 |
| C4 | **投放知识库** (支柱③) | `services/knowledge/`：媒体变更/行业基线/策略&效果 三表 + 向量；`kb_query` 工具；`market_research` 改 KB 后端；主动学习 | 决策前自动检索并自适应 |
| C5 | **归因模型层** (GPT #5) | Last-touch→Linear MTA→Data-driven MTA，作为 `observe` 指标输入 | 归因更科学 |
| C6 | **主动日报/异动推送** (GPT #8) | 飞书/企微/邮件 Webhook + 每日定时日报 | 异常自动推送、日报自动生成 |

### Phase D — 领先市场（对应 GPT 🟢，可选/长期）
| 编号 | 内容 |
|---|---|
| D1 | **RL 出价优化**：`SimulationEngine`→Gymnasium→Ray RLlib，参数经 `StrategyStore` 持久化 |
| D2 | **多 Agent 协作**：Analyst/Strategist/Executor/Reporter 拆分 |
| D3 | **Agent-to-Agent 媒体协议**：前置"跨平台统一 API 层" |
| D4 | **复杂目标分解**：LLM 规划 + DSPy 式提示优化（"Q3 CPI<$2 且 ROAS>3x"） |

---

## 3. 首迭代建议（Phase A 已于 2026-07-11 完成 ✅，Phase B/C/D 待启动）

**推荐从 Phase A 起步**，但 A2/A3 受外部依赖制约（Meta 被封、MMP 需密钥），因此首迭代务实拆法：

- **必做（无外部依赖）**：A1 持久化（纯内部，立刻消除重启即失）、B1 ToolCatalog 骨架、C4 知识库表结构（不依赖真实数据即可建）。
- **可并行准备（代码先行、真实接通等条件）**：A2 写 Google/TikTok Connector 代码 + Mock fallback；A3 写 MMP 摄取适配层（用测试/沙箱数据验证）。
- **延后到条件具备**：Meta 真实接通（等账号解封）、真实 MMP 推全（等密钥）。

这样首迭代既能立刻消除最大工程风险（持久化），又能把"接真实数据"的代码与护栏备好，条件一到即切换。

---

## 4. 待确认决策点

1. **首迭代范围**：Phase A 地基优先 / Phase B 能力优先 / A+B 合并？
2. **真实渠道策略**（Meta 被封下如何推进 A2/A3）：先写代码+Mock 待命 / 先攻 Google+TikTok / 先接 MMP 归因(沙箱)？
3. **知识库向量检索**：本地 embeddings 自建 / 接已有向量服务？
4. **策略治理人审强度**：默认 L2 批准阈值定多高？
5. **Phase D 是否纳入本轮规划**：仅列路线不实现 / 挑 D1(RL) 做原型？

---

## 5. 与既有设计文档关系

- 本文件是**统一路线图（canonical）**，吸收了 `AGENT_NEXT_ITERATION_DESIGN.md`（三支柱设计稿）的全部内容，并补齐 GPT 文档的"数据地基"与"市场差距"条目。
- 执行时建议以本文件为基准，三支柱稿可视为本文件的"能力供给/复盘/知识库"三节详设。
