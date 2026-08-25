# SmartUA - 智能投放平台

基于大模型意图识别驱动的智能投放平台，支持多App多租户、操作安全分级控制、效果闭环学习优化。

## ✨ 项目状态

**v1.0 初体验版本已完成 ✅** - 可直接启动体验完整功能

| 模块 | 状态 | 说明 |
|------|------|------|
| 后端API | ✅ 完成 | Campaign/AdGroup/Ad/Creative 完整CRUD |
| 前端页面 | ✅ 完成 | Dashboard + Campaign详情 + 素材管理 |
| 认证系统 | ✅ 完成 | JWT + RBAC 权限模型 |
| 数据初始化 | ✅ 完成 | 数据库初始化脚本 + demo数据 |
| 意图引擎 | ⏳ 待完善 | 骨架已完成，待接入真实LLM |

---

## ⚡ Quick Start

```bash
make setup      # 装后端依赖 + alembic migrate + 种子数据 + 前端 npm install
make dev        # 并行起后端 :8000 + 前端 :5173（vite proxy 已配）
make test       # 后端 pytest
make db-reset   # 清库 + migrate + 重新 seed
```

- `make dev` 用 `&` 并行起前后端；Ctrl-C 后若 uvicorn 未退出，`pkill -f uvicorn`，或用 `make dev-backend` / `make dev-frontend` 分开跑。
- 默认账号见下方「快速开始」。
- 无 LLM 凭证时自动走规则引擎兜底，不影响体验。

---

## 核心特性

### 🤖 大模型意图识别（规划中）
- **自然语言驱动**：用自然语言描述投放操作，AI自动解析并执行
- **示例**："把美国昨天ROI低于0.5的所有campaign都暂停"

### 🔒 操作安全分级（Human-in-the-loop / Human-on-the-loop）
| 级别 | 模式 | 触发条件 |
|------|------|----------|
| **L0** | Human-on-the-loop | 低风险操作（素材轮换、告警检查），自动执行 |
| **L1** | 一键确认 | 中等风险（暂停、小幅预算调整），10分钟超时自动执行 |
| **L2** | 人工审核 | 高风险（大幅提价、大预算），必须人工确认 |
| **L3** | 仅建议 | 首次/未知操作，仅给建议，不执行 |

### 📊 四层数据架构
- **ODS层**：原始API数据
- **DWD层**：标准化事实表（媒体、MMP）
- **DWS层**：指标聚合（ROI360、素材效果）
- **ADS层**：应用数据服务（健康度、告警、报表）

### 🎯 已实现功能模块
1. **投放大盘 Dashboard**：Campaign列表、趋势图表、告警中心
2. **Campaign详情页**：概览、AdGroup列表、广告创意、设置面板
3. **素材管理中心**：创意列表、多维度筛选、详情预览
4. **异常预警中心**：ROI下降、CPI上升、花费异常检测
5. **四层运营实体模型**：Campaign → AdGroup → Ad → Creative

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend: React 18 + Vite + Ant Design                      │
├─────────────────────────────────────────────────────────────┤
│  Backend: FastAPI + SQLAlchemy + Pydantic                    │
├─────────────────────────────────────────────────────────────┤
│  Intent Engine: LLM-based Natural Language Understanding      │
├─────────────────────────────────────────────────────────────┤
│  Database: SQLite (dev) / PostgreSQL (prod)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 后端启动

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 初始化数据库（生成完整Demo数据，仅需执行一次）
python init_db.py

# 可选：重置密码
python reset_password.py

# 启动服务
python main.py
```

访问 API 文档: http://localhost:8000/docs

### 2. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问前端: http://localhost:5173

### 3. 默认账号

| 角色 | 邮箱 | 密码 |
|------|------|------|
| 管理员 | admin@smartua.com | admin123 |
| 优化师 | optimizer1@smartua.com | opt123 |
| 分析师 | analyst1@smartua.com | ana123 |
| 财务 | finance@smartua.com | fin123 |

---

## 📁 项目结构

```
SmartUA/
├── backend/
│   ├── app/
│   │   ├── api/v1/                  # API路由
│   │   │   ├── auth.py              # 认证API
│   │   │   ├── campaign.py          # Campaign/AdGroup/Ad API
│   │   │   ├── creative.py          # 素材API
│   │   │   ├── data.py              # 数据/告警API
│   │   │   └── connectors.py        # 连接器API
│   │   ├── core/                    # 安全、工具
│   │   ├── models/                  # 数据模型
│   │   │   ├── campaign.py          # Campaign → AdGroup → Ad
│   │   │   ├── creative.py          # 素材模型
│   │   │   └── data.py              # 告警、报表模型
│   │   ├── schemas/                 # Pydantic Schema
│   │   ├── services/                # 业务逻辑
│   │   │   └── intent_engine.py     # 意图识别引擎
│   │   └── db/                      # 数据库
│   ├── scripts/
│   ├── init_db.py                   # 数据库初始化脚本 ⭐
│   ├── init_alerts.py               # 告警数据初始化
│   ├── reset_password.py            # 密码重置工具
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx       # 投放大盘
│   │   │   ├── CampaignDetail.jsx  # Campaign详情
│   │   │   └── CreativeManagement.jsx # 素材管理
│   │   ├── api.js                  # API封装
│   │   └── App.jsx
│   └── vite.config.js
├── docs/                            # 设计文档
│   ├── ARCHITECTURE.md             # 系统架构设计
│   ├── API_REFERENCE.md            # API参考文档
│   └── CONNECTOR_DESIGN.md         # 连接器设计
└── README.md
```

---

## 🧩 数据模型

### 核心业务表（运营四层模型）
- **apps**: 多租户App定义
- **campaigns**: 投放活动（Campaign）
- **ad_groups**: 广告组（AdGroup）
- **ads**: 广告（Ad）
- **creatives**: 素材（Creative）
- **users/roles/permissions**: RBAC权限体系

### ADS应用层表
- **alerts**: 异常预警记录
- **campaign_health**: Campaign健康度快照
- **dashboard_cache**: Dashboard缓存

### 数据关系

```
Campaign (1) ── (N) AdGroup (1) ── (N) Ad (N) ── (1) Creative
```

---

## 🎯 开发计划

### ✅ 已完成
- [x] 后端API骨架（FastAPI + SQLAlchemy）
- [x] 数据库Schema设计
- [x] 四层运营实体模型（Campaign/AdGroup/Ad/Creative）
- [x] RBAC权限体系
- [x] 数据库初始化脚本（含Demo数据）
- [x] React前端基础框架
- [x] Dashboard投放大盘页面
- [x] Campaign详情页面（含嵌套数据加载）
- [x] Creative素材管理页面
- [x] 告警中心模块

### 📅 待完成
- [ ] 意图识别引擎（接入真实LLM）
- [ ] 操作安全分级控制
- [ ] 真实媒体平台API对接
- [ ] 效果自动回扫与策略学习
- [ ] LLM路由（Claude/GPT/DeepSeek）
- [ ] 四层数仓ODS/DWD/DWS实现

---

## 设计理念

1. **Data First**: 数据驱动，从ROI360到Campaign健康度层层递进
2. **Safety First**: 操作分级，AI建议、人做决策，L0自动执行
3. **Closed Loop**: 每个操作都有效果跟踪，模型持续学习优化
4. **Multi-tenant**: 原生支持多App多租户，数据隔离、权限隔离
5. **No Mock Data**: 前端无本地Mock，所有数据来自后端API（数据库层Demo）

---

## 🐛 常见问题

### Q: 前端白屏怎么办？
A: 检查：
1. 后端是否正常启动（http://localhost:8000/docs）
2. 浏览器Console是否有API请求错误
3. 确认已执行 `python init_db.py` 初始化数据

### Q: 如何重置密码？
```bash
cd backend
python reset_password.py
```

### Q: 如何重新初始化数据？
```bash
cd backend
rm smartua.db
python init_db.py
python init_alerts.py
```

### Q: API返回的数值是字符串？
A: SQLAlchemy Decimal类型JSON序列化后为字符串，前端统一用 `Number(val)` + `isNaN()` 安全处理。

---

## License

MIT

*版本：v1.0 | 最后更新：2026-06-28*
