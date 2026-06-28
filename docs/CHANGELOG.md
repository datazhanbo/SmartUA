# 更新日志

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

## 开发路线图

### v1.1 (规划中)
- [ ] 意图引擎接入真实 LLM
- [ ] 操作安全分级控制实现
- [ ] Meta Ads 连接器对接
- [ ] 效果自动回扫机制

### v1.2 (规划中)
- [ ] 多模型路由 (Claude/GPT/DeepSeek)
- [ ] 自动化策略引擎
- [ ] A/B 测试框架
- [ ] 报表导出功能

### v2.0 (远期)
- [ ] 四层数仓 ODS/DWD/DWS/ADS 完整实现
- [ ] ClickHouse OLAP 查询加速
- [ ] 完整媒体平台对接 (Meta/Google/TikTok)
- [ ] 闭环学习系统
