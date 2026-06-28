# 🚀 SmartUA - 智能投放平台

## ✅ 已完成 - MVP版本

### 📁 项目结构
```
SmartUA/
├── backend/
│   ├── main.py                           # FastAPI 入口
│   ├── app/
│   │   ├── api/v1/                       # API路由
│   │   │   ├── auth.py                   # 认证、登录
│   │   │   ├── apps.py                   # 多App管理
│   │   │   ├── data.py                   # ROI360、健康度、告警
│   │   │   └── intent.py                 # 意图识别、策略
│   │   ├── core/security.py              # JWT、密码、权限
│   │   ├── models/                        # SQLAlchemy模型
│   │   │   ├── sys.py                    # 系统表(用户、角色、App)
│   │   │   ├── data.py                   # 数仓表(ODS/DWD/DWS/ADS)
│   │   │   └── intent.py                 # 意图执行、策略模板
│   │   ├── schemas/                       # Pydantic Schema
│   │   └── services/
│   │       └── intent_engine.py          # 🤖 意图识别引擎
│   └── scripts/
│       └── generate_mock_data.py         # 测试数据生成
└── smartua.db                            # SQLite数据库
```

---

## 🎯 核心功能 (已实现)

### 1. 🔐 多租户权限体系
- ✅ 多App隔离（多租户）
- ✅ RBAC角色权限（5种内置角色）
- ✅ JWT认证
- ✅ 用户-App绑定

### 2. 📊 四层数据架构
- ✅ **ODS层**: 原始API数据连接器运行记录
- ✅ **DWD层**: 标准化事实表（媒体、MMP）
- ✅ **DWS层**: ROI360聚合表（7天ROI、CPI、留存）
- ✅ **ADS层**: Campaign健康度快照、异常告警

### 3. 🤖 意图识别引擎
```python
# 自然语言输入 -> 标准化投放操作
intent_text = "把ROI低于0.5的Campaign暂停"

result = engine.parse(intent_text)
# {
#   "intent_class": "campaign.pause",
#   "confidence": 0.857,
#   "risk_level": "L1",           # 一键确认
#   "parameters_extracted": {"roi_threshold": 0.5},
#   "affected_campaigns": [...],  # 受影响的Campaign
#   "estimated_impact": {...},    # 花费影响预估
# }
```

### 4. ⚠️ 操作安全分级 (Human-in-the-loop)
| 级别 | 模式 | 触发条件 | 典型操作 |
|------|------|----------|----------|
| **L0** | 自动执行 | 低风险操作 | 素材轮换、告警检查 |
| **L1** | 一键确认 | 中等风险 | 暂停Campaign、小幅预算调整 |
| **L2** | 人工审核 | 高风险操作 | 提价>50%、单日提额>$1000 |
| **L3** | 仅建议 | 首次/未知操作 | 新建Campaign、大策略调整 |

### 5. 📈 投放分析API
- ✅ `GET /api/v1/data/roi360` - ROI多维分析
- ✅ `GET /api/v1/data/campaign-health` - Campaign健康度
- ✅ `GET /api/v1/data/alerts` - 异常告警
- ✅ `POST /api/v1/intent/parse` - 意图识别
- ✅ `POST /api/v1/intent/execute` - 创建执行任务
- ✅ `POST /api/v1/intent/approve` - 审批操作

---

## 🧪 测试数据 (已生成)
| 表 | 记录数 |
|----|--------|
| 应用 (App) | 2个 |
| 用户 | 4个 |
| 角色 | 5种 |
| 媒体日报 (fact_media_daily) | 750行 |
| MMP归因日报 (fact_mmp_daily) | 658行 |
| ROI360聚合 (agg_ua_daily) | 750行 |
| Campaign健康度快照 | 25个 |
| 策略模板 | 6个 |

---

## 🚀 快速启动

```bash
cd backend

# 生成测试数据（首次运行）
python3 scripts/generate_mock_data.py

# 启动API服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 访问
# API文档: http://localhost:8000/docs
# 测试账号: admin@smartua.com / admin123
```

---

## 💡 架构设计亮点

1. **意图驱动**: 自然语言描述投放需求，AI自动解析执行
2. **分级信任**: AI不直接执行高风险操作，Human-in-the-loop把关
3. **闭环学习**: 每次操作记录效果，不断优化意图识别准确率
4. **四层数仓**: ODS→DWD→DWS→ADS，数据治理规范
5. **多租户隔离**: 原生支持多App/多产品投放管理

---

## 🔮 下一阶段规划

1. **前端UI**: React + Tailwind + Antd 控制台
2. **LLM集成**: Claude/GPT深度集成，提升意图理解准确率
3. **自动执行**: L0级别操作全自动执行，效果回扫验证
4. **策略引擎**: 基于规则+ML的优化建议
5. **真实API对接**: Meta/Google/TikTok Marketing API对接

