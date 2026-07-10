# 更新日志

## v1.6.0 - 2026-07-10

> 本期核心：**Phase 4 主动式自治（Proactive Autonomy）**。Agent 从"人召唤才动"升级为
> "主动守护"——APScheduler 周期巡检账户，检测异常后按 L0-L3 分级自主处置：低风险自动执行、
> 高风险推给你审批、账户被封主动告警。复用 Phase 1~3 全部能力（Tool Registry / 记忆 / 策略），
> 是「进化成熟态」的收口。

### ✨ 新功能

**Phase 4 — 主动式自治（Proactive Autonomy）**：
- 🛡 `backend/app/services/agent_runtime/autonomy.py`：
  - `AnomalyDetector`：从实时账户状态检测 5 类异常——**CPI 飙升 / ROI 跌破阈值 / 素材疲劳 /
    花费异常 / 账户被封（Meta appeal 等）**。ROI 跌破阈值**优先采用 Phase 3 已学策略**
    （`pause_roi_threshold`），回退默认 1.0，体现"处置质量随经验提升"。
  - `AutonomyEngine.scan()`：检测→分级处置。L0（如换素材）**自动执行**；L1/L2（如暂停/调预算）
    生成一条"主动提案"进入**人在环审批队列**（复用 AgentSession/Step 审批流）；仅通知类
    （花费异常、账户被封）**不自动改动**，留给人工判断——主动≠失控。
  - `AutonomyStore`：进程内告警流 + 扫描历史 + 调度配置；同 (异常类型, campaign) **冷却去重**
    （`agent_autonomy_cooldown_scans`），避免每轮重复提案。
  - APScheduler `BackgroundScheduler` 接入（`start_scheduler` / `stop_scheduler`），周期巡检。
- 🌐 `backend/app/api/v1/agent.py` 新增主动自治端点：
  `GET /agent/autonomy/status`（调度状态）、`GET /agent/autonomy/alerts`（告警流）、
  `POST /agent/autonomy/scan`（手动巡检）、`POST /agent/autonomy/toggle`（启停调度）。
  审批端点 `/agent/sessions/{id}/approve` 回写关联告警状态，前端告警流随之更新。
- ⚙️ `config.py` 新增 Phase 4 开关：`agent_autonomy_enabled` / `agent_autonomy_interval_seconds`
  / `agent_autonomy_cooldown_scans` / `agent_fatigue_threshold_days` / `agent_monitor_app_ids`。
- 🖥 `frontend/src/pages/AgentConsole.jsx`：右侧「智能体大脑」升级为 **Tabs**，新增
  「🛡 主动自治」页——监控状态（开/关 + 最近扫描 + 待审批数）、立即巡检、启停调度、
  告警流（待审批内联批准/驳回、查看关联会话）。`frontend/src/api.js` 新增 `autonomy*` 方法。
- 🧪 `scripts/demo_phase4.py`：端到端演示（疲劳自动轮换 / ROI 跌破待审批 / 账户被封告警 / 冷却去重 /
  数据驱动阈值自适应 / 调度器可用性）。
- 🧪 `scripts/test_autonomy_http.py`：真实 HTTP 调用链验证（登录→状态→巡检→审批→告警流→启停）。

### 🔧 架构优化
- ✅ `SimulationEngine` 新增 `account_status` 单例字段（被封/恢复），使"账户被封"状态在多次
  `get_connector` 间持久（修复早期 per-实例丢失的 bug）。`live_summary()` 补 `creative_age` /
  `daily_budget` 字段，供疲劳/花费检测使用。
- ✅ 安全护栏在主动场景同样生效：任何写动作都走 Risk 分级，L1/L2 绝不自动执行。

### ⚠️ 风险与权衡
- 主动自治默认开启（`agent_autonomy_enabled=True`），间隔 120s 仅用于演示；生产建议 ≥300s。
- L0 仅用于低风险动作（当前为换素材）；暂停/调预算/调出价一律人工确认，绝不自动。
- 告警流与会话仓目前为进程内单例，重启即失；生产需落库（与 EpisodicMemory 同批补齐）。

---

## v1.5.0 - 2026-07-10

> 本期核心：**把 Phase 1~3 的后端能力真正接到交互界面**。新增「智能体控制台」页面，
> 优化师可在浏览器里用自然语言给 Agent 下目标、在页面上审批高风险动作、查看记忆/策略/复盘——
> 至此 SmartUA 从"能跑后端的 agent"变成"人能用起来的 agent"。

### ✨ 新功能

**前端对接 Agent Loop（智能体控制台）**：
- 🖥 `frontend/src/pages/AgentConsole.jsx`：**多轮 Agent 对话 UI**
  - 启动目标 → 步骤时间线（💭推理 / 👁观察 / ✅已执行 / ⏳待审批 / 🏁结论）
  - **L1/L2 动作内联审批**（批准→续跑 / 驳回→重新规划），对应后端 `/agent/sessions/{id}/approve`
  - 多轮追问输入框（对应 `/agent/sessions/{id}/message`）
  - 右侧「智能体大脑」面板：**已学策略**（GET `/agent/strategy`）、**经验复盘**（POST `/agent/reflect`）、
    「学习策略」/「重置策略」按钮（对应 `/agent/strategy/learn`、`/agent/strategy/reset`）
- 🔌 `frontend/src/api.js`：新增 `agentAPI`（10 个方法，完整覆盖 `/agent/*` 端点）
- 🧭 `frontend/src/App.jsx` + `components/MainLayout.jsx`：注册 `/agent` 路由与侧边栏「智能体控制台」导航项

### 🐛 修复
- 修复 `_record_execution` 向 `IntentExecution` 误传不存在的 `approval_required` 字段导致
  **审批 L1 动作时 500**（前端点「批准执行」即触发）。该 bug 由端到端 HTTP 调用链验证发现并修复。

### ⚠️ 说明
- 旧 `IntentCenter`（单轮「解析→弹窗→执行」）保留并存，作为遗留流程入口。
- 运行需：后端 `uvicorn main:app --port 8000` + 前端 `npm run dev`（Vite 代理 `/api → :8000`），
  且需先用有效账号登录（Agent 端点均要求 JWT）。

---

## v1.4.0 - 2026-07-10

> 本期核心：把 Phase 2 的「经历」编译成**可学习、可迁移、可持久**的策略参数，
> 让规划器从"硬编码默认值"升级为"数据驱动的策略"——这标志着「进化能力」正式收口
> （经验 → 记忆 → 策略 → 跨账户/跨进程复用）。

### ✨ 新功能

**Phase 3 — 策略自演化（Strategy Self-Evolution）**：
- 🎯 `backend/app/services/agent_runtime/strategy.py`：
  - `StrategyRule` + `StrategyStore`：从 Episode 记忆**挖掘**可学习参数
    （`budget_increase_cap` 加预算增幅上限 / `pause_roi_threshold` 暂停阈值 / `rotate_when_roi_below` 换素材触发下限），
    每条带 `confidence`（依样本量）+ `n_samples` + `source`。
  - `advise(key, default)`：规划器查询接口，无/低置信度时优雅回退默认（不阻塞主流程）。
  - **落盘持久化**（JSON）：解决 Phase 2「重启即失」风险，策略可跨进程、跨账户迁移。
- 🔗 `loop._rule_based_decide`：预算增幅与暂停阈值**优先咨询策略层**，回退 Phase 2 记忆收敛，再回退硬编码默认。
- 🌐 `backend/app/api/v1/agent.py` 新增策略端点：
  `POST /agent/strategy/learn`（记忆→策略+落盘）、`GET /agent/strategy`、`POST /agent/strategy/reset`。
- ⚙️ `config.agent_strategy_path`：策略落盘路径，默认 `backend/data/strategy.json`。
- 🛠 `scripts/demo_phase3.py`：演示「多账户累积 → learn 策略 → 模拟重启+新账户迁移」全链路。

### 🔧 架构优化
- ✅ `_budget` 工具把增幅 `_pct` 透传进 Episode，供策略层挖掘「历史最优增幅」（数据闭环打通）。
- ✅ `AgentContext` 新增 `strategy` 字段，`__init__` 导出 `StrategyStore/StrategyRule/StrategyLearnResult/get_strategy`。

### ⚠️ 风险与权衡
- 当前策略参数为**标量阈值**学习（而非原规划中的"策略 A/B / 元学习优化提示词 / 四层数仓特征"），
  后者仍列为后续增强方向；Phase 3 已交付"可学习策略参数"这一核心收口。
- 策略置信度随样本量线性增长（封顶 1.0 @5 样本），样本过少时仍回退默认，避免过拟合噪声。

---

## v1.3.0 - 2026-07-10

> 本期核心：把 Agent Loop 的"记忆/反思空壳"填上，让系统**记住并复盘、越做越准**
> （Phase 2 记忆 + 反思闭环）。这是把"进化能力"彻底补回来的最后一环。

### ✨ 新功能

**Phase 2 — 记忆与反思（Episodic Memory + Reflection）**：
- 🧠 `backend/app/services/agent_runtime/memory.py`：
  - `Episode`：单次写动作的完整经历（目标 / 动作 / `pre_state` 动作前快照 / `impact_2h/24h/7d_json` / 结果）。
  - `EpisodicMemory`：进程内单例、**跨会话持久**——正是「跨任务学习」的载体（本周 A 账户踩的坑，下周 B 账户仍能调用）。聚合出 per-action 统计，并给出 `suggest_budget_increase_cap()` 等决策修正。
- 🔍 `backend/app/services/agent_runtime/reflection.py`：`Reflector.reflect()` 把 Episode
  复盘为「自然语言摘要 + 启发式规则」（止损 / 预算边际递减→增幅收敛≤10% / 素材疲劳短期提振 /
  提价伤 ROI），规则引擎兜底、可选 LLM 增强。
- 🔁 **闭环关键**：`loop._rule_based_decide` 的预算分支 consult 记忆，当历史加预算 7d 平均 ΔROI
  转负时**自动收敛增幅**；`AgentLoop.reflect()` 新增复盘入口。
- 🌐 `backend/app/api/v1/agent.py`：新增 `POST /agent/reflect`（全局复盘）、
  `POST /agent/sessions/{id}/reflect`（按会话复盘）。
- 🛠 `scripts/demo_phase2.py`：场景A 多目标执行→沉淀 Episode；场景B 复盘提取规则；场景C
  新账户+类似目标→规划器 consult 记忆把预算增幅从 +20% 收敛到 +10%（验证"越做越准"）。

### 🔧 架构优化
- ✅ 写动作执行后由 `tools._write` **自动沉淀 Episode**（`AgentContext.memory` 注入），对上层透明。
- ✅ `config.agent_reflection_enabled`：可一键关闭记忆/反思（降级到 Phase 1 行为）。

### ⚠️ 风险与权衡
- 记忆目前为进程内单例，重启即失；生产需落库为 `EpisodicMemory` 表（与 `ActionLog` 互为补充：
  审计看"做了什么"，记忆看"做得好不好、下次怎么改"）。
- 反思规则为确定性抽取（可解释、可复现）；接入 LLM 生成自然语言复盘为可选增强，未阻塞主流程。

---

## v1.1.0 - 2026-07-10

> 本期核心：在 Meta 账户被封（今日新号直接触发 appeal）的现实约束下，先把"进化能力"缺失的
> **数据土壤**补回来——用有状态因果模拟引擎替代无状态随机 mock，使"动作→指标"存在真实因果链，
> 为 Agent Loop（Phase 1）与记忆/反思闭环（Phase 2）提供可复现、可量化、可被 Agent 动作影响的
> 连续数据。

### ✨ 新功能

**Agentic 升级评审与路线图**：
- 📄 `docs/AGENTIC_AD_PLATFORM_UPGRADE.md`：澄清 SmartUA 当前定位是
  "**意图驱动的投放控制台**"而非 agentic platform；给出 Phase 0~4 升级方案
  （真实闭环 → Agent Loop → 记忆反思 → 策略自演化 → 主动自治）。
- 明确核心架构思想：**平台做"身体+护栏"，Agent Loop 做"大脑"，Tool/Skill Registry 做桥接**。

**Phase 0 — 真实执行数据土壤（Mock 因果模拟引擎）**：
- 🧪 `backend/app/services/simulation/engine.py`：有状态因果模拟引擎。预算饱和（边际 ROI 递减）、
  素材疲劳、换素材短期提振、提价伤 ROI 等因果效应均可解释、可复现（seed）、可量化。
- 🔌 `backend/app/services/connectors/mock_media.py`：注册为 `mock` 渠道的 `MockMediaConnector`。
  写操作**真实修改模拟状态**，拉取历史会反映动作效果 → 形成因果闭环。
- 🔁 `ConnectorFactory` 新增 `"mock"` 渠道。Meta 账户恢复后只需把工厂里的 `"mock"` 换回 `"meta"`，
  上层 Agent Loop 与意图引擎零改动（Connector 抽象的价值）。
- 🛠 `scripts/demo_mock_media.py`：独立验证"暂停/加预算/换素材"三类动作的因果效果。

### ⚠️ 风险与权衡
- 本期仅补数据土壤；Agent Loop（规划/ReAct/多轮/人在环）为 Phase 1（见 v1.2.0），
  记忆/反思为 Phase 2（见 v1.3.0）。
- `mock` 渠道为开发期数据土壤，所有"真实执行"均为确定性模拟，不消耗真实预算；
  回采影响基于日粒度模拟，2h 影响为线性外推近似。

---

## v1.2.0 - 2026-07-10

> 本期核心：把"单轮解析器"升级为"会规划、会多轮、会等人在环确认"的 **Agent Loop（Phase 1）**，
> 进化引擎就位。（记忆/反思空壳仍留待 v1.3.0。）

### ✨ 新功能

**Phase 1 — Agent Loop（进化的引擎）**：
- 🧠 `backend/app/services/agent_runtime/`：
  - `session.py`：多轮会话状态（目标 / 步骤 / 待审批项 / 上下文），内存会话仓库。
  - `tools.py`：Tool/Skill Registry，把"观察/筛选/预测影响/暂停/调预算/调出价/换素材/报表"
    封装为带 L0-L3 风险元数据的工具；写工具真实执行并回填 `impact_2h/24h/7d_json`。
  - `loop.py`：ReAct 风格循环 `think → select tool → (execute | propose) → observe → think again`；
    **规则引擎兜底**（无 LLM 自动降级）+ LLM 规划路径；**L1/L2 高风险动作走人在环审批**，
    批准后续跑，驳回后重新规划。
- 🌐 `backend/app/api/v1/agent.py`：多轮 Agent 对话 API
  （`POST /agent/sessions`、`.../approve`、`.../message`、`GET /agent/sessions/{id}`）。
- 🛠 `scripts/demo_agent_loop.py`：模拟"模糊目标 → 拆多步 → L1 审批 → 真实执行 → 观察 →
  回采影响 → 终态"的完整闭环。

### 🔧 架构优化
- ✅ LLM 解耦 + 优雅降级原则贯穿 Agent Loop（无 API Key 时走规则引擎，不报错）。
- ✅ 真实执行与审计解耦：无 DB / 无第三方包时 demo 仍可运行（审计写库为可选项）。
- ✅ `BaseConnector.apply_action(action, entity_id, **params)` 通用写动作分发器：Agent Loop
  的写工具统一调用它（而非具体连接器方法），与连接器彻底解耦；Meta 接回时上层零改动。
- ✅ `SimulationEngine.live_summary()`：基于实时状态（而非历史快照）的账户概览，使 Agent
  能在动作后立即看到最新状态（如暂停后该 campaign 立即显示 PAUSED、spend=0），避免基于
  过期快照重复提议。

### ⚠️ 风险与权衡
- 本期 Agent Loop 的"记忆/反思"仍是空壳（v1.3.0 待做）；多轮会话目前为进程内内存仓库，
  重启即失（生产需落库 + 接 Episodic Memory）。
- `mock` 渠道为开发期数据土壤，所有"真实执行"均为确定性模拟。

---

## v1.0.0 - 2026-06-28

### ✨ 新功能

**前端页面**：
- 🎯 Dashboard 投放大盘页面完整实现
  - 4个统计卡片（今日花费、整体ROI、安装量、活跃Campaign）
  - ROI 趋势图表（ECharts）
  - 告警列表（支持查看详情、标记已处理）
  - Campaign 数据表格（支持排序、过滤）
  - 告警详情弹窗（含影响分析、建议动作）

- 📊 Campaign 详情页（四 Tab 结构）
  - 概览：Campaign 统计卡片 + 趋势图 + AdGroup 列表
  - AdGroup 详情：AdGroup 统计 + 广告列表表格
  - 广告创意：创意卡片网格 + 素材优化操作
  - 设置：Campaign 完整配置信息

- 🎬 素材管理页面
  - 4个统计卡片（素材总数、总花费、平均ROI、总安装量）
  - 素材列表表格（支持按类型、设计师、状态筛选）
  - 素材详情弹窗（含效果指标、关联 AdGroup）
  - 类型标签页筛选（全部/视频/图片/试玩/轮播）

**后端 API**：
- 🔐 完整认证系统
  - JWT Token 登录
  - RBAC 权限模型（admin/optimizer/analyst/finance）
  - 用户-应用绑定（多租户）

- 📦 Campaign 完整 CRUD
  - Campaign → AdGroup → Ad 嵌套返回
  - 支持按状态、媒体、国家筛选
  - 所有数值字段 Decimal 精确计算

- 🎨 Creative 素材管理 API
  - 完整 CRUD
  - 支持标签、设计师、类型管理
  - 表现分 + 趋势指标

- ⚠️ 告警系统 API
  - ROI 下降、CPI 上升、花费异常告警
  - 告警详情含影响 Campaign 列表
  - 建议动作自动生成
  - 标记已处理接口

### 🔧 架构优化

**数据一致性**：
- ✅ 前端无本地 Mock 数据原则落地
- ✅ 所有 Demo 数据在数据库初始化层生成
- ✅ 四层实体状态标签体系统一
- ✅ 数值字段安全渲染标准化（Number() + isNaN()）

**API 设计**：
- ✅ Campaign API 嵌套返回完整层级，避免 N+1 请求
- ✅ Decimal 类型统一序列化为字符串，前端安全转换
- ✅ 空状态友好处理（草稿 Campaign、空 AdGroup 等）

**开发工具**：
- ✅ 数据库一键初始化脚本 `init_db.py`
- ✅ 密码重置工具 `reset_password.py`
- ✅ 告警数据初始化脚本 `init_alerts.py`

### 📝 文档

- ✅ README.md 快速开始指南更新
- ✅ ARCHITECTURE.md 系统架构设计文档
- ✅ API_REFERENCE.md API 参考文档
- ✅ CONNECTOR_DESIGN.md 连接器设计文档

### 🐛 Bug 修复

- 修复前端白屏问题：API 数值字段安全处理
- 修复 Campaign 详情页空白状态：空 AdGroup 友好展示
- 修复语法错误：JSX 括号匹配问题
- 修复数值渲染错误：NaN 统一显示为 `-`

### 📦 技术栈

**前端**：
- React 18 + Vite 5
- Ant Design 5
- ECharts 5
- Axios

**后端**：
- FastAPI 0.109
- SQLAlchemy 2.0
- Pydantic 2.0
- SQLite (开发) / PostgreSQL (生产)
- Passlib (密码哈希)
- JWT (认证)

---

## v0.2.0 - 2026-06-27

### ✨ 新功能

- 连接器系统骨架设计
- 意图引擎骨架实现
- 四层数仓架构设计
- 操作安全分级矩阵设计

---

## v0.1.0 - 2026-06-27

### ✨ 新功能

- 初始项目骨架
- 系统架构设计文档
- API 路由骨架

---

## 开发路线图（对齐 Agentic 升级 Phase 0~4）

### ✅ v1.1.0 (已完成, 2026-07-10)
- [x] 定位评审与 Phase 0~4 路线图
- [x] Mock 因果模拟引擎 + `mock` 渠道（替代无状态随机 mock）
- [x] Agent Loop（规划 + ReAct + 多轮 + 人在环）

### ✅ v1.2 / v1.3 / v1.4 / v1.5 (已完成) — Phase 1~3 + 前端对接
- [x] Phase 1 Agent Loop（规划 + ReAct + 多轮 + 人在环）
- [x] Phase 2 记忆与反思（Episodic Memory + Reflection）
- [x] Phase 3 策略自演化（StrategyStore 落盘、跨账户迁移）
- [x] 前端「智能体控制台」对接（多轮对话 / 审批 / 记忆 / 策略 / 复盘）

### ✅ v1.6.0 (已完成, 2026-07-10) — Phase 4 主动式自治
- [x] APScheduler 周期巡检 + 5 类异常检测（CPI/ROI/疲劳/花费/账户被封）
- [x] 分级处置：L0 自动执行、L1/L2 人在环审批、仅通知不自动改动
- [x] 主动汇报（告警流 + 监控面板）+ ROI 阈值数据驱动（复用 Phase 3 策略）
- [x] 冷却去重，避免重复打扰

### ⏳ v2.0 (远期) — 生产化与增强
- [ ] Episodic Memory / 会话仓 / 告警流落库（目前进程内单例，重启即失）
- [ ] 主动汇报升级：日报 / 异动摘要推送（邮件 / 企微 / 飞书）
- [ ] Meta 账户恢复后切回真实 Connector（上层零改动）
- [ ] 四层数仓 ODS/DWD/DWS/ADS + ClickHouse 加速
- [ ] 策略 A/B + 元学习（自优化提示词/启发式）
