# SmartUA 架构与版本演进独立 Review

> Review 日期：2026-07-21  
> Review 范围：`docs/` 下版本历史、架构、连接器、Agent Runtime、LLM 路由、扩展性、API、用户手册和后续路线图。  
> Review 方法：以文档交叉核对为主，重点检查版本叙事、架构边界、生产安全和路线优先级；本文不是逐行代码审计。

---

## 1. 总体判断

SmartUA 的演进方向是成立的：项目已经从 v1.0 的 UA 数据控制台，连续补齐 Agent Loop、记忆、策略、主动自治、LLM 流式交互与状态持久化，形成了较完整的“感知—决策—行动—复盘”骨架。

当前最需要解决的不是继续扩充工具数量，而是把“演示可运行”升级为“真实资金场景下可证明正确”。文档中有三类能力被过早标记为“已完成”：

1. **代码路径具备，不等于真实链路已验证**：Google/TikTok 在无凭证、SDK 缺失或调用异常时回退 Mock，真实媒体和真实 MMP 仍未形成稳定闭环。
2. **状态落入 SQLite，不等于支持多实例**：进程内缓存、后台线程、APScheduler、策略 JSON 和跨进程协调仍然限制水平扩展。
3. **存在 `impact_2h/24h/7d` 字段，不等于完成真实因果学习**：真实 Connector 的影响估计可为全零，实际延迟回采、对照组和归因治理尚未落地。

因此，建议把现阶段定位统一为：

> **已具备 Agentic 投放平台的功能骨架，并进入真实链路与生产安全验证阶段。**

不建议直接描述为“真实闭环已完成”或“可多实例”。

---

## 2. 版本演进梳理

| 阶段 | 版本 | 主要变化 | 架构意义 |
|---|---|---|---|
| 项目骨架 | v0.1–v0.2 | API、连接器、意图引擎、四层数仓和风险分级设计 | 建立平台化边界 |
| 数据控制台 | v1.0 | Dashboard、Campaign/Creative、告警、JWT、RBAC、多租户 | 形成可操作的 UA 管理平台 |
| 因果沙盘 | v1.1 | 有状态 `SimulationEngine`、MockMediaConnector | 为动作后效果观察提供可复现数据 |
| Agent Loop | v1.2 | ReAct、多轮会话、Tool Registry、人在环审批 | 从单轮意图解析转向目标驱动循环 |
| 记忆与反思 | v1.3 | Episodic Memory、Reflection、经验反哺规划 | 建立跨会话学习入口 |
| 策略学习 | v1.4 | StrategyStore、阈值学习、JSON 持久化 | 从经验记录走向参数化决策 |
| 产品化交互 | v1.5 | Agent Console、审批、复盘、策略 UI | Agent 能力进入用户工作流 |
| 主动自治 | v1.6 | APScheduler、异常检测、主动提案、L0 自动处置 | 从被动响应转向周期守护 |
| 真实 LLM 交互 | v1.7 | Ark、SSE、流式展示、abort/redirect、市场检索 | 增强规划能力和交互实时性 |
| 数据地基补强 | v1.8 | 会话/记忆/告警 SQLite 持久化、TikTok/Google 路径、MMP 指标接地 | 缓解重启丢失，开始接近真实媒体链路 |
| 下一阶段规划 | Phase B–D | ToolCatalog、MCP/CLI/API、策略治理、知识库、A/B、RL、多 Agent | 目标从功能闭环转向能力扩张 |

### 演进中的关键架构转折

1. **v1.0 → v1.2**：系统核心从 CRUD/意图解析切换到 Agent Runtime。
2. **v1.2 → v1.4**：Agent 从“会执行”升级为“能积累经验并改变参数”。
3. **v1.5 → v1.6**：人在环从会话内审批扩展到系统主动发现异常后的审批队列。
4. **v1.7 → v1.8**：项目开始补齐真实 LLM、持久化与真实媒体连接，但生产语义尚未闭合。

---

## 3. 做得好的部分

### 3.1 平台与 Agent 的职责划分清晰

“平台做身体和护栏、Agent Loop 做大脑、Tool Registry 做桥接”是正确的核心抽象（`ARCHITECTURE_v2.md:11-21`）。Agent 不直接操作媒体，而是经过带风险元数据的工具层，这比把权限和执行逻辑写进 Prompt 更可靠。

### 3.2 降级思路适合早期迭代

LLM 不可用时回退规则规划器，使本地开发和演示不依赖外部模型（`LLM_ROUTING_v2.md:11-16`、`LLM_ROUTING_v2.md:70-79`）。这降低了开发门槛，也使决策行为具备最低可复现性。

### 3.3 Mock 从随机数据升级为因果沙盘

有状态 SimulationEngine 比无状态随机 Mock 更适合验证 Agent Loop、记忆和策略更新（`CONNECTOR_DESIGN_v2.md:47-60`）。其预算饱和、素材疲劳和出价影响模型虽然简化，但具备可解释性，适合作为测试环境。

### 3.4 风险分级与人在环贯穿主流程

L1/L2 动作进入审批而非由 LLM 直接执行，主动自治也复用同一套审批流（`ARCHITECTURE_v2.md:111-123`、`ARCHITECTURE_v2.md:151-156`）。这是进入真实资金场景的必要基础。

### 3.5 文档保留了历史版本

v1/v2 文档并存，能看出项目从“意图控制台”到 Agentic 平台的演进过程。对于复盘设计决策有价值，但需要进一步建立明确的当前版本入口。

---

## 4. 主要问题与风险

## 4.1 P0：必须先解决的正确性与资金安全问题

### P0-1：真实 Connector 的静默 Mock 回退会制造“假成功”

`CHANGELOG.md:37-43` 说明 Google Ads 在缺凭证、SDK 不可用等情况下自动回退 Mock；路线图又把 A2 标为“已完成”（`AGENT_ITERATION_ROADMAP.md:49-54`）。对开发环境这是便利，对生产环境却是高风险：用户可能认为暂停、调预算或换素材已经作用于真实账户，实际上只修改了模拟状态。

**建议：**

- 明确区分 `mock`、`sandbox`、`live` 三种运行模式。
- `live` 模式必须 fail-closed：凭证、SDK、权限或网络异常时直接失败，不允许回退 Mock。
- 所有 Connector 响应强制返回 `execution_mode`、`provider_request_id`、`account_id` 和 `verified_at`。
- UI 对 Mock/Sandbox 使用永久醒目标识，审计日志记录实际执行目标。

**验收标准：**在 live 配置下移除 SDK 或使用无效凭证，写动作明确失败，且数据库、UI 和审计中均不能出现“执行成功”。

### P0-2：外部写动作缺少幂等、确认与对账协议

现有设计强调数据拉取的 `source_row_hash` 幂等，但没有给媒体写动作定义同等级别的幂等协议。网络超时可能发生在媒体已经接受请求之后，简单重试会导致重复调预算、重复创建或状态错判。

**建议：**

- 每个写动作生成不可变 `action_id` / `idempotency_key`。
- 建立动作状态机：`proposed → approved → dispatching → accepted → verified | failed | unknown`。
- 保存请求摘要、前置状态、媒体 request ID、响应和最终回读状态。
- 对超时结果标记 `unknown`，通过查询媒体真实状态进行 reconciliation，禁止盲目重试。
- 使用 Outbox/Job 表把“批准”与“外部执行”解耦。

**验收标准：**模拟“媒体已执行但响应超时”，重复调度不会产生第二次预算变更，最终可通过回读收敛到 `verified`。

### P0-3：审批存在时效性和 TOCTOU 风险

当前流程是先生成审批步骤，等待人工批准后继续执行（`ARCHITECTURE_v2.md:111-119`）。投放指标和预算可能在等待期间已变化，原建议可能不再安全。

**建议：**

- 审批对象冻结完整动作参数、目标实体版本和决策快照。
- 增加 `expires_at`，过期后必须重新规划。
- 执行前重新校验账户状态、预算、实体状态和风险级别。
- 若变化超过阈值，终止旧审批并生成差异说明，不得静默套用旧批准。

**验收标准：**审批等待期间预算或 Campaign 状态发生变化时，旧批准不能直接执行。

### P0-4：Agent 对象级多租户隔离没有被完整证明

架构反复声明 JWT、RBAC 和用户-App 绑定（`ARCHITECTURE_v2.md:207-209`），但 Agent Session、Episode、Strategy、Alert 的读取与执行边界没有在文档中定义清楚。仅“端点要求 JWT”不足以防止已登录用户通过 session ID 访问其他 App 的会话或审批。

**建议：**

- 所有 Agent 运行时实体强制包含 `tenant_id/app_id/account_id/created_by`。
- 每次 GET、审批、redirect、abort、reflect 和 strategy learn 均做对象级授权。
- Strategy 默认按 tenant + app + channel + country 分区；跨账户迁移必须显式授权和脱敏。
- 添加跨租户 IDOR 自动化测试。

**验收标准：**用户 A 获取用户 B 的 session/alert ID 后，所有读取和写入请求均返回 404/403，且不会泄露对象是否存在。

### P0-5：真实“影响回采”与当前学习数据语义不一致

真实 Connector 的 `simulate_impact()` 可返回全零，缺 MMP 时 ROI 为 `None`（`CHANGELOG.md:22-29`）；但路线图将 A3 描述为“真实归因接地完成”（`AGENT_ITERATION_ROADMAP.md:49-54`）。这只能说明查询路径不会崩溃，不能证明真实归因闭环或策略学习有效。

**建议：**

- 把 `predicted_impact`、`observed_impact`、`attributed_impact` 分成独立字段，禁止混用。
- 动作执行后创建 2h/24h/7d 延迟回采任务，而不是立即将预测结果当作结果。
- 记录归因窗口、数据新鲜度、时区、币种、MMP 来源和完整性状态。
- 数据不足时 Episode 标记为 `pending/unusable`，不得进入 Strategy 学习。
- 先采用 matched control / difference-in-differences 等可解释方法，再考虑复杂模型。

**验收标准：**没有真实回采或归因质量不合格的 Episode 不会改变生产策略参数。

### P0-6：SSE query token 有泄露风险

`CHANGELOG.md:68-72` 明确为兼容 EventSource 将 token 放入 query。URL 可能进入代理日志、浏览器历史、监控平台和 Referer。

**建议：**

- 优先使用 `fetch` 流式读取并通过 Authorization header 认证。
- 或使用短期、单次、仅绑定 session 的 stream ticket，TTL 控制在分钟级。
- 配置 `Referrer-Policy: no-referrer`，日志和 APM 对 token 参数强制脱敏。
- 禁止长期 JWT 出现在 URL。

**验收标准：**反向代理、应用日志、浏览器历史和监控事件中均看不到长期访问令牌。

---

## 4.2 P1：进入生产前应解决的架构问题

### P1-1：SQLite 持久化不代表可多实例

路线图声称 A1 “可多实例”（`AGENT_ITERATION_ROADMAP.md:52`），但扩展文档明确指出内存单例、策略 JSON、模拟引擎和 APScheduler 会在多 worker 下分叉（`SCALING_UPGRADE.md:18-31`）。两者矛盾。

此外，双轨缓存 + SQLite 的方案还需要定义缓存失效、并发覆盖和步骤追加语义。WAL 与 `busy_timeout` 只缓解锁竞争，不提供跨进程一致性。

**建议：**

- 立即删除“可多实例”表述，标记为“单进程重启可恢复”。
- 将 PostgreSQL、版本列/乐观锁、原子 step append 和共享任务队列列为生产前置，而不是等到 30 人并发后才启动。
- StrategyStore 从 JSON 迁移到带版本和作用域的数据库表。

### P1-2：后台 daemon thread 不是可靠执行引擎

v1.7 将 Agent Loop 放到 daemon thread（`CHANGELOG.md:68-71`）。即使会话已持久化，进程退出仍可能中断正在执行的动作；重启后也缺少任务认领、续跑、超时和孤儿任务恢复语义。abort/redirect 标志如果仅依赖进程内对象，多实例下也不能可靠生效。

**建议：**

- 把 Agent run/step 作为持久化 Job，由独立 worker 通过 lease 认领。
- 每一步写入 checkpoint；外部写动作遵循 P0-2 的幂等状态机。
- abort/redirect 写入数据库或消息总线，worker 定期检查。
- 明确定义进程崩溃后的恢复策略：续跑、重新规划或转人工。

### P1-3：APScheduler 与 Web 进程耦合

多副本会各自启动调度器，导致重复扫描和重复提案。`SCALING_UPGRADE.md:126-144` 已识别该问题，但它不应仅作为未来扩容优化；一旦部署方式变化就会触发正确性事故。

**建议：**生产中将调度从 Web 进程剥离为唯一 scheduler/worker，或使用数据库 advisory lock/leader lease；告警去重使用数据库唯一键而不是进程内冷却计数。

### P1-4：风险级别是静态工具属性，不能覆盖真实业务风险

文档把 `rotate_creative` 定义为 L0 自动写（`ARCHITECTURE_v2.md:125-141`）。同一个工具在低预算测试 Campaign 与高预算主 Campaign 上风险不同；工具名也无法表达批量范围、预算变化幅度和账户状态。

**建议：**建立动态 Policy Engine，风险由以下因素共同决定：

- 动作类型与可逆性；
- 单次/累计预算影响；
- 目标实体数量和近 24h spend；
- 数据新鲜度、模型置信度和异常程度；
- 用户角色、环境和账户白名单。

生产默认 deny-by-default，并提供全局 kill switch、单账户自动化上限和每日变更额度。

### P1-5：原始模型 reasoning 不应作为产品审计理由

v1.7 将 `reasoning_content` 逐 token 展示（`CHANGELOG.md:68-72`）。原始模型思维过程不稳定、不可验证，也可能包含敏感上下文；它不适合作为审批依据或审计证据。

**建议：**展示结构化决策说明，而非原始 reasoning：使用的数据、数据时间、触发规则、候选方案、预期影响、风险级别和不确定性。审计记录应基于输入、工具调用、策略版本和结果，而不是自然语言思维链。

### P1-6：外部检索、MCP、CLI/API 扩展会显著扩大攻击面

下一阶段计划动态注册 MCP、CLI 和 OpenAPI 工具，并拟通过名称启发式判断风险（`AGENT_NEXT_ITERATION_DESIGN.md:38-48`）。这是不安全的：`get/query` 也可能泄露数据，外部网页内容可能 Prompt Injection，OpenAPI 定义也不能证明接口安全。

**建议：**

- 工具必须由管理员显式登记 schema、权限、数据分级和副作用，禁止仅靠名称推断风险。
- MCP/网页返回内容一律视为不可信数据，不得改变系统指令或审批策略。
- CLI 使用独立容器/沙箱、只读文件系统、无默认网络、CPU/内存/时间限制和固定命令模板。
- API 工具采用域名白名单、凭证隔离、响应大小限制和敏感字段脱敏。
- 在完成威胁模型与策略引擎前，不建议上线通用 `shell_tool`。

### P1-7：凭证治理在架构文档中缺失

文档描述了 `connector_credentials` 和环境变量回退，但未说明静态加密、密钥管理、轮换、访问审计、最小权限和撤销。

**建议：**凭证密文存储，密钥置于 KMS/Secret Manager；按 tenant/account 隔离；token 刷新采用单飞锁；日志不得打印请求 header；提供过期预警、撤销和权限范围展示。

---

## 4.3 P2：可维护性、可观测性与产品表达问题

### P2-1：文档版本体系混乱且大量内容停留在 v1.6

`ARCHITECTURE_v2.md`、`CONNECTOR_DESIGN_v2.md`、`LLM_ROUTING_v2.md`、`API_REFERENCE_v2.md` 均基于 v1.6，而当前路线图和 Changelog 已到 v1.8。典型冲突包括：

- `ARCHITECTURE_v2.md:61-67` 和 `ARCHITECTURE_v2.md:229-234` 仍称会话、记忆、告警为进程内状态；v1.8 已加入 SQLite。
- `ARCHITECTURE_v2.md:82-85` 仍称默认平台为 Mock；Changelog 称已切 Google。
- `LLM_ROUTING_v2.md:19-28` 未包含 v1.7 已接入的 Ark，模型与成本信息也已过时。
- `SCALING_UPGRADE.md:20-30` 的状态基线仍是 v1.6。

**建议：**

- 建立 `docs/README.md` 作为唯一文档入口，标明 canonical、historical、proposal、superseded。
- 当前架构只维护一份，历史版移入 `docs/archive/v1/`。
- 每份文档增加 `applies_to_version`、`status`、`last_verified_commit`、`owner`。
- 通过 CI 检查 API OpenAPI 快照、配置项和文档中的关键路径是否漂移。

### P2-2：“四层数仓”叙事超过实际完成度

文档常将 ODS/DWD/DWS/ADS 作为已具备的平台身体，但 `CONNECTOR_DESIGN_v2.md:137-144` 又说明 DWS/ADS 为后续增强。建议把“目标架构”和“当前实现”分栏，避免把设计图当作已交付能力。

### P2-3：缺少生产 SLO 和数据质量契约

当前可观测重点是 connector run 和同步行数，但 Agent 系统还需要：

- Connector 成功率、限流率、数据新鲜度和落库延迟；
- Agent 每步延迟、LLM 成本/失败率/降级率；
- 审批等待时长、动作 verify 成功率、unknown 动作数量；
- 自动化动作造成的预算变化、回滚率和人工否决率；
- 按 tenant/app/channel 的 trace_id 全链路追踪。

建议为真实链路定义 SLO，并以 SLO 而非“脚本断言通过”作为完成标准。

### P2-4：数据库演进方式需要正式化

文档提到启动时 `create_all` 建表。进入真实环境后应采用 Alembic 等迁移系统，支持 schema version、升级前检查、回滚方案和数据回填；不能依赖应用启动隐式修改结构。

### P2-5：演示账号和 Token 存储需要环境隔离

API/用户手册公开演示账号密码（`API_REFERENCE_v2.md:50-62`、`USER_MANUAL_v2.md:29-38`），前端使用 localStorage 保存 JWT（`SCALING_UPGRADE.md:184-188`）。

**建议：**生产构建禁止初始化演示账号；首次管理员密码随机生成并强制修改。Web 端优先使用 Secure + HttpOnly + SameSite Cookie，或采用短期 access token + 安全 refresh token，并补齐 CSP/XSS 防护。

---

## 5. 对当前路线图的调整建议

现有路线图把 Phase B 的 ToolCatalog/MCP/CLI、Phase C 的知识库和策略扩维列为下一阶段重点。独立 review 建议改变顺序：

### 建议的新 Phase P0：Production Truth & Safety

1. Live/Mock 严格隔离，live fail-closed。
2. 外部动作幂等状态机、Outbox、回读验证和对账。
3. Agent 全对象 tenant/app/account 隔离。
4. 审批过期、快照冻结、执行前重校验。
5. 真实影响延迟回采与可学习数据质量门槛。
6. SSE 认证修正、凭证治理和审计脱敏。

### 建议的新 Phase P1：Durable Runtime

1. PostgreSQL + 正式迁移体系。
2. Agent Job/Step 持久化任务执行器，替换 daemon thread。
3. 独立调度器与跨进程去重。
4. Strategy 版本化、作用域隔离和回滚。
5. 指标、日志、trace、SLO 和异常演练。

### Phase B：有限扩充工具

只先接 2–3 个高价值只读工具，例如真实归因查询、Creative Intelligence、数据质量检查。完成显式权限模型和 Prompt Injection 防护后，再考虑 MCP 动态注册；通用 CLI 最后做。

### Phase C：策略治理与知识库

在真实 Episode 达到足够样本且质量可证明后，再扩充策略参数、A/B 和知识库。否则只是用更多结构包装模拟或污染数据。

### Phase D：RL / 多 Agent

继续保留为远期研究，不建议在真实动作可靠性、因果回采和策略治理完成前投入。多 Agent 会放大成本、延迟和调试难度，但不会自动提高正确性。

---

## 6. 建议的 6 周落地顺序

### 第 1–2 周：堵住假成功和越权

- Live/Mock 模式隔离；
- 写动作状态机和 execution receipt；
- Agent 对象级多租户测试；
- SSE token 改造；
- 审批 expiry + revalidation。

### 第 3–4 周：建立可靠运行时

- PostgreSQL/Alembic；
- 持久化 Job + worker lease；
- 调度器独立；
- 崩溃恢复、重复投递和媒体超时演练。

### 第 5–6 周：完成一个真实闭环

只选一个渠道、一个账户、一个低风险动作：

> 读取真实数据 → 生成提案 → 人工审批 → 幂等执行 → 回读确认 → 2h/24h/7d 回采 → Episode 质量检查 → 人工批准策略更新。

当这条链路可以重复通过，且不存在 Mock 混入、跨租户泄露、重复执行和不可解释的策略更新时，再宣布“真实闭环完成”。

---

## 7. 建议建立的验收门禁

### 安全门禁

- 跨租户 IDOR 测试全绿；
- live 环境任何 Mock 回退测试必须失败；
- Token/凭证扫描无泄露；
- 所有写动作具备审批或 Policy Engine 判定记录。

### 正确性门禁

- 外部动作重复投递不重复生效；
- timeout/unknown 可通过 reconciliation 收敛；
- 审批后状态变化会触发重新评估；
- 无真实归因的数据不进入策略学习。

### 可靠性门禁

- 执行中杀进程，任务可恢复且不重复写媒体；
- 启动两个副本，不产生重复调度和重复告警；
- DB/LLM/媒体 API 短时不可用时状态可解释、可重试、可审计。

### 产品门禁

- UI 永久显示数据来源、环境和执行模式；
- 每次建议展示数据时间、依据、影响范围、置信度和风险；
- 审批人能看到动作前后差异及过期状态；
- 管理员可以一键停用全部自动写动作。

---

## 8. 最终建议

SmartUA 已经完成了较有价值的 Agentic 架构原型，下一阶段应从“继续增加智能能力”转向“证明现有智能能力不会误操作真实预算”。

最高优先级不是 MCP、CLI、RL 或多 Agent，而是以下四件事：

1. **真实与模拟严格隔离；**
2. **外部动作幂等、可确认、可对账；**
3. **运行时持久、可恢复、可多实例协调；**
4. **学习数据真实、可归因、受治理。**

完成这四项后，SmartUA 才能从“Agentic 功能骨架”进入“可托付真实投放账户”的阶段。
