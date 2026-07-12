# SmartUA Agent 下一阶段迭代设计（v1.8+）

> 目标：把"会聊天的初级 agent"升级为"有工具、会学习、有记忆的增长操盘手"。
> 三大迭代重点：① 让 agent 更聪明（工具 / MCP / CLI / API 供给）② 通过复盘学习策略 ③ 构建投放知识库。
> 状态：设计稿（待评审确认 Phase 优先级）。

---

## 0. 结论（先讲结论）

**可行，且三件事不是并列堆功能，而是同一套"感知—决策—记忆—学习"闭环的三层扩张：**

| 重点 | 对应层 | 解决什么 |
|---|---|---|
| 工具 / MCP / CLI / API 供给 | **行动 & 外界感知供给层** | agent 能做什么、能"看见"什么 |
| 复盘学习策略 | **认知层** | 决策质量随经验持续提升 |
| 投放知识库 | **记忆 / 知识层** | 结构化沉淀媒体 / 行业 / 策略知识，可检索、可复用 |

三者通过**既有的 `AgentLoop` + `ToolRegistry` + `EpisodicMemory` + `StrategyStore`** 串成闭环，每个 Phase 都能独立验证、灰度上线，不需要推倒重来。

---

## 1. 现状基线（已经具备的零件）

- **`ToolRegistry`（tools.py）**：L0–L3 风险元数据 + read/write 标注，已注册 `budget` / `pause` / `rotate` / `market_research` 等。
- **`AgentLoop`（loop.py）**：ReAct 循环 + LLM 规划 / 规则兜底 + L1/L2 人在环审批 + 流式思考 + `abort` / `redirect` 中途改向。
- **`EpisodicMemory`（memory.py）**：动作执行后自动沉淀 `Episode`（含 `impact_2h / 24h / 7d_json`）。
- **`Reflector`（reflection.py）**：复盘为摘要 + 启发式规则。
- **`StrategyStore`（strategy.py）**：从 Episode 挖掘 `budget_increase_cap` / `pause_roi_threshold` / `rotate_when_roi_below`，落盘 JSON、可跨账户迁移。
- **仿真引擎（simulation/engine.py）+ mock_media**：闭环试验数据土壤，无需真金白银。
- **`market_research` 工具**：真实搜索优先 + `BENCHMARK_DB` 兜底。
- **MCP 连接器框架**（`~/.workbuddy/mcp.json` / `connector:*`）已存在，可作为外部能力桥接。

→ 所有新能力都是在上述零件上"加料"。

---

## 2. 重点一：让 agent 更聪明（工具 / MCP / CLI / API 供给）

### 2.1 ToolCatalog 自动注册
新增 `services/agent_runtime/catalog.py`，统一扫描四类来源并注入 `ToolRegistry`：

1. **内置工具**（现有）：budget / pause / rotate / bid / audience + market_research。
2. **MCP 工具**：`MCPToolBridge` 读取已连接 MCP server 的 tool 清单，动态注册；每个 tool 带 risk 标注（由 server 声明，或启发式推断：`query`/`get`=read/L0，mutate=write/L1–L2）。
3. **CLI 工具**：`shell_tool`（沙箱）：allowlist 命令（python / sqlite / curl 白名单域名）、超时、禁止 `rm`/`dd` 等破坏指令；返回 stdout。
4. **API 工具**：`api_tool` 读取已注册 OpenAPI / JSON spec，自动生成"调用某接口"工具（AppsFlyer / Sensor Tower / Singular 拉数）。

**风险分类启发式**：只读 = L0；写但不花钱 = L1；写且涉及预算 / 账户 = L2；不可逆删除 = L3。

### 2.2 关键新工具（让 agent 真正"看见市场"）

| 工具 | 类型 | 来源 | 价值 |
|---|---|---|---|
| `creative_intel` | read | Meta Ad Library / TikTok Creative Center（web / MCP） | 竞品素材情报，指导素材迭代 |
| `trending_topics` | read | Google Trends / news API | 品类热点，抓量时机 |
| `analytics_query` | read | Adjust / AppsFlyer（API / MCP） | 真实归因 ROAS / LTV，校正平台内数据 |
| `store_reviews` | read | App Store / Play 评论抓取 | 留存 / QA 信号，反推素材承诺偏差 |
| `data_script` | read | CLI（sandbox python） | 自定义取数 / 可视化分析 |

### 2.3 更聪明的规划
- **Plan-and-Execute**：planner 先产出多步计划（含工具调用序列）→ executor 执行 → observer 把结果回灌；失败时 replan。
- **Critic 校验**：计划执行前由 critic LLM 做可行性 / 风险复核（高 L 级动作强制）。
- **Few-shot from memory**：从成功 `Episode` 抽取工具使用轨迹，作为 planner 的少样本，提升首轮决策质量。

---

## 3. 重点二：通过复盘学习策略（深化 Phase 2 / 3）

### 3.1 复盘从"摘要"升级为"因果归因"
`Reflector` 产出三类产物：
1. 结果摘要（已有）；
2. **因果归因**：动作 → 指标 delta（如"暂停 camp_x → 24h CPI −12%"），来自 `impact_*_json` 对比；
3. **可学习参数候选**：基于归因提出 `StrategyStore` 待更新项 + 置信度。

### 3.2 StrategyStore 参数扩维
在现有 3 个参数基础上扩展（保留落盘 JSON + 跨账户迁移）：

```
budget_shift_step / budget_shift_max / budget_increase_cap
pause_roi_below / pause_cpi_above
scale_when_roas_above / scale_pct
creative_rotation_interval_days / creative_fatigue_ctr_drop
bid_adjust_on_cpi_delta
audience_expansion_trigger
channel_preference_weights{category,country}
working_hours
```

### 3.3 学习方法
- **Episodic→Parametric**：每个完成 Episode 的 `impact` 拟合参数（移动平均 / 简单回归 / 多臂 Bandit）。
- **反事实推理**：用仿真引擎回放"若早一天暂停"，估计反事实 ROI，更新先验。
- **贝叶斯更新**：每个观测更新参数后验（Normal / Beta），`confidence` = 后验落在容差内的质量。
- **跨账户迁移**：相似账户间用收缩（shrinkage / hierarchical）迁移，避免小样本过拟合。

### 3.4 策略治理（人在环）
- 低置信度策略变更需 L2 人工批准；前端「智能体大脑」面板展示**策略 diff**（如"pause_roi_below 1.0→0.9，依据 12 个 Episode，置信 0.7，批准 / 驳回 / 回滚"）。
- 策略**版本化 + 一键回滚**；夜间批处理学习任务产出策略验证报告。

---

## 4. 重点三：构建投放知识库（媒体 / 行业 / 策略）

### 4.1 三类知识
1. **媒体变更**：政策 / 格式 / API / 事件（ATT、TikTok 美区、新广告位…）。
   结构：`{channel, date, type, summary, impact, affected_actions, recommended_adaptation, source_url}`。
2. **行业基线**：CPI / CPA / ROAS / CVR × 品类 × 国家 × 渠道。
   结构：`{category, country, channel, metric, value, percentile, date, source, confidence}`。
3. **内部策略迭代与效果**：`StrategyStore` + Episode outcomes。
   结构：`{strategy_key, value_history, episodes_applied, measured_effect, status}`。

### 4.2 KB 架构（`services/knowledge/`）
- **存储**：结构化（SQLite：`media_events` / `baselines` / `strategies` 三表）+ 向量（embeddings，语义检索非结构化笔记）。
- **摄取**：
  - 媒体变更：定时爬取官方 changelog（web / MCP 工具）→ 结构化入库；
  - 行业基线：`market_research` 运行结果持久化 + 版本快照；
  - 策略：来自复盘（§3）。
- **检索 / RAG**：agent 新增 `kb_query` 工具（语义 + 结构化过滤），决策前先检索 grounding。例：动手前查"近期 Meta 影响 iOS 定向的政策变更？"→ 命中 → 自适应。
- **主动学习**：agent 用基线做决策、实际偏差大时，回写 baseline `confidence`（置信衰减 / 提升）。

### 4.3 market_research 升级为 KB 后端
改为"**先查本地 KB（快、鲜）→ 缺失 / 过期再联网 → 回写 KB**"，让外部知识可累积、可进化，不再每次都现搜。

---

## 5. 统一架构（三层闭环）

```
┌─────────────────────────────────────────────────────────────┐
│ 供给层 Supply Layer  —  ToolCatalog → ToolRegistry           │
│  [内置] [MCP Bridge] [CLI 沙箱] [API 自动生成]               │
└───────────────────────────┬─────────────────────────────────┘
                            │ uses
┌───────────────────────────▼─────────────────────────────────┐
│ 认知层 Cognition Layer                                        │
│   Planner ──▶ AgentLoop(Plan→Exec→Observe)                   │
│                ▲              │                              │
│                │ consult      ▼                              │
│          StrategyStore ◀── Reflector(因果归因)               │
└───────────────────────────┬─────────────────────────────────┘
                            │ write / read
┌───────────────────────────▼─────────────────────────────────┐
│ 知识层 Knowledge Layer — KnowledgeBase (SQLite + 向量)        │
│   [媒体变更] [行业基线] [策略&效果]  ◀── kb_query 检索 grounding │
└─────────────────────────────────────────────────────────────┘
```
- AgentLoop 通过 `ToolRegistry` 调用工具；动作后触发 `Reflector`；
- `Reflector` 写 `StrategyStore` 与 `KnowledgeBase`；
- `StrategyStore` 被 `Planner` 咨询、`KnowledgeBase` 被 `AgentLoop` 经 `kb_query` 检索，形成闭环。

---

## 6. 分阶段路线图

| Phase | 内容 | 验收标准 |
|---|---|---|
| **Phase 4 — 工具供给** | ToolCatalog + MCP 桥（媒体 + 分析 2 个 MCP）+ CLI 沙箱 + API 自动生成 | agent 能拉竞品素材、查归因 ROAS、跑数据脚本 |
| **Phase 5 — 深度策略学习** | StrategyStore 扩维 + 贝叶斯 / 回归更新 + 反事实仿真 + 策略治理 UI + 夜间批学习 | 多账户 20+ Episode 后关键参数收敛且可解释 |
| **Phase 6 — 知识库** | KB 服务（SQLite + 向量）+ 摄取管线（媒体变更 / 基线 / 策略）+ `kb_query` + 主动学习 | 决策前自动检索到相关媒体变更 / 基线并自适应 |
| **Phase 7 — 集成与提自治** | KB↔策略↔工具闭环；agent 主动响应媒体变更；安全动作默认升 L1、护栏保留 | 整体 autonomy 提升、人工干预率下降 |

---

## 7. 可行性与风险

**可行性**：所有零件已存在，每 Phase 增量可验证；风险元数据已支撑安全升级；mock_media + 仿真引擎提供无成本试验场。

**风险 / 缓解**：
- 真实媒体 API 易变 / 需鉴权 → 先 MCP 桥 + mock，真实接入按渠道灰度；
- 策略学习过拟合小样本 → 贝叶斯先验 + 跨账户收缩 + 低置信强制人工；
- KB 脏数据 → 来源置信标注 + 主动学习衰减 + 人工校正入口；
- 工具爆炸导致规划失控 → ToolCatalog 分类 + critic 复核 + L 级审批。

---

## 8. 待确认决策点

1. 优先做哪个 Phase？（建议 **Phase 4 打底**——因为 2/3 都依赖"更多可观测信号"）
2. MCP 优先接哪类？（媒体 / 分析 / 文档）
3. 知识库向量检索自建（本地 embeddings）还是接已有向量服务？
4. 策略治理的人审强度（默认 L2 批准阈值）？
