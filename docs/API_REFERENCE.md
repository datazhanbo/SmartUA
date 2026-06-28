# SmartUA API 参考文档

## 目录

- [核心概念速查](#核心概念速查)
- [认证](#认证)
- [认证 API](#认证-api)
- [Campaign API](#campaign-api)
- [Creative API](#creative-api)
- [数据与告警 API](#数据与告警-api)
- [连接器 API](#连接器-api)
- [意图引擎 API](#意图引擎-api)

---

## 核心概念速查

### 🔑 四层运营实体模型

所有投放平台通用的四层数据模型：

```
Campaign (活动)
    ↓ 1:N
AdGroup (广告组)
    ↓ 1:N
Ad (广告)
    ↓ N:1
Creative (素材)
```

### 📊 数据类型注意事项

**Decimal → String 序列化问题**：

> ⚠️ 重要：API 返回的所有数值字段（roi, spend, cpi, ctr 等）都是 **字符串类型**。

**前端统一处理方式**：
```javascript
// ✅ 正确做法
const numVal = Number(val)
return !isNaN(numVal) ? numVal.toFixed(2) : '-'

// ❌ 错误做法（直接使用会导致 NaN 白屏）
val.toFixed(2)
```

---

## 认证

所有 API 请求需要在 Header 中携带 Bearer Token：

```bash
Authorization: Bearer <access_token>
```

### 基础 URL

```
http://localhost:8000/api/v1
```

---

## 认证 API

### 登录

```http
POST /auth/login
Content-Type: application/json

{
  "email": "admin@smartua.com",
  "password": "admin123"
}
```

**响应**：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_at": "2026-06-29T10:00:00"
}
```

### 获取当前用户信息

```http
GET /auth/me
Authorization: Bearer <token>
```

**响应**：
```json
{
  "id": 1,
  "email": "admin@smartua.com",
  "username": "System Admin",
  "phone": null,
  "department": "Technology",
  "status": "active",
  "last_login_at": "2026-06-28T08:30:00",
  "roles": ["admin"],
  "apps": [{"id": 1, "name": "Block Blast"}]
}
```

---

## Campaign API

### 获取 Campaign 列表

```http
GET /campaigns?app_id=1&status=running
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | int | ✅ | 应用ID |
| status | string | ❌ | 按状态过滤 |
| media | string | ❌ | 按媒体过滤 |
| country | string | ❌ | 按国家过滤 |

**响应示例**：
```json
[
  {
    "id": 5,
    "name": "Campaign_US_Android",
    "app_id": 1,
    "media": "Meta",
    "dsp": "Meta Ads",
    "campaign_type": "App Install",
    "objective": "Installs",
    "bid_strategy": "Target Cost",
    "optimization_goal": "App Install",
    "country": "US",
    "platform": "Android",
    "status": "running",
    "health": "excellent",
    "budget": "10000.00",
    "spend": "5200.50",
    "roi": "2.350000",
    "cpi": "1.85",
    "target_cpi": "2.00",
    "impressions": 520000,
    "clicks": 26000,
    "installs": 2800,
    "ctr": "5.000000",
    "last_update": "2026-06-28T08:00:00"
  }
]
```

### 获取 Campaign 详情（含嵌套数据）⭐

```http
GET /campaigns/{id}
```

**响应**：返回完整的层级嵌套数据，前端无需额外请求

```json
{
  "id": 5,
  "name": "Campaign_US_Android",
  "media": "Meta",
  "status": "running",
  "roi": "2.350000",
  "spend": "5200.50",
  "...": "...",
  
  "ad_groups": [
    {
      "id": 8,
      "campaign_id": 5,
      "name": "US-Broad-Target",
      "status": "running",
      "roi": "2.150000",
      "spend": "2800.00",
      "cpi": "1.92",
      "impressions": 280000,
      "clicks": 14000,
      "installs": 1458,
      
      "ads": [
        {
          "id": 1,
          "ad_group_id": 8,
          "name": "Ad-Video-Funny",
          "creative_id": 5,
          "status": "running",
          "roi": "2.050000",
          "spend": "1200.00",
          "impressions": 120000,
          "clicks": 6000,
          "installs": 625,
          "ctr": "5.000000",
          "cpc": "0.2000",
          "cpi": "1.92",
          "conversion_rate": "10.420000"
        }
      ]
    }
  ]
}
```

> 💡 **设计说明**：一次性返回 Campaign → AdGroup → Ad 完整嵌套结构，避免前端 N+1 请求瀑布。

### 获取 Campaign 的 AdGroup 列表

```http
GET /campaigns/{id}/adgroups
```

### 获取 AdGroup 的 Ad 列表

```http
GET /adgroups/{id}/ads
```

---

## Creative API

### 获取 Creative 列表

```http
GET /creatives?app_id=1&type=video
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | int | ✅ | 应用ID |
| type | string | ❌ | 按类型过滤 video/image/playable/carousel |
| status | string | ❌ | 按状态过滤 |

**响应示例**：
```json
[
  {
    "id": 5,
    "app_id": 1,
    "name": "US_Carousel_Features",
    "type": "carousel",
    "format": "jpg",
    "file_size": 5242880,
    "duration": null,
    "resolution": "1080x1080",
    "url": "https://example.com/creative5.html",
    "thumbnail_url": "https://picsum.photos/200/300?random=5",
    "designer": "张三",
    "tags": ["轮播", "玩法", "US", "多图"],
    "status": "active",
    "performance_score": 85,
    "trend": "up",
    "spend": "5200.00",
    "impressions": 520000,
    "clicks": 26000,
    "installs": 2800,
    "ctr": "5.000000",
    "cpc": "0.2000",
    "cpi": "1.86",
    "roi": "2.150000",
    "conversion_rate": "10.770000",
    "last_used_at": null,
    "created_at": "2026-06-25T10:00:00"
  }
]
```

### 获取单个 Creative 详情

```http
GET /creatives/{id}
```

---

## 数据与告警 API

### 获取告警列表

```http
GET /data/alerts?app_id=1&severity=high
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| app_id | int | ✅ | 应用ID |
| severity | string | ❌ | high / medium |
| status | string | ❌ | open / resolved |

**响应示例**：
```json
[
  {
    "id": 1,
    "app_id": 1,
    "alert_type": "roi_drop",
    "severity": "high",
    "message": "Campaign_DE_UAC ROI 下降 35%",
    "campaign_id": "3",
    "campaign_name": "Campaign_DE_UAC",
    "metric": "ROI D7",
    "current_value": "0.65",
    "previous_value": "1.00",
    "threshold": "0.8",
    "trend": "down",
    "affected_campaigns": [
      {"id": "3", "name": "Campaign_DE_UAC", "spend": 5200, "roi": 0.65}
    ],
    "suggested_actions": [
      "降低出价 10% 以控制 CPI",
      "检查素材 CTR 表现",
      "考虑暂停 ROI < 0.5 的广告组"
    ],
    "detected_at": "2026-06-28T08:30:00",
    "description": "ROI 连续 3 天呈下降趋势",
    "status": "open"
  }
]
```

### 标记告警已处理

```http
PUT /data/alerts/{id}/resolve
```

**响应**：
```json
{
  "success": true,
  "message": "告警已处理"
}
```

---

## 连接器 API（骨架已完成）

### 获取可用连接器列表

```http
GET /connectors/
```

### 创建凭证

```http
POST /connectors/credentials
Content-Type: application/json

{
  "platform": "meta",
  "account_name": "Meta Production Account",
  "account_id": "act_123456789",
  "auth_type": "oauth2",
  "credentials_json": {
    "access_token": "EAACxxxxx..."
  },
  "sync_frequency": "hourly",
  "auto_sync_enabled": true,
  "notes": "主账号凭证"
}
```

### 拉取数据

```http
POST /connectors/pull?platform=meta&date_from=2026-06-01&date_to=2026-06-07
```

### DWS 层聚合

```http
POST /connectors/sync/dws?date_from=2026-06-01&date_to=2026-06-07
```

### 获取同步运行列表

```http
GET /connectors/runs?connector=meta&status=success&limit=50
```

---

## 意图引擎 API（骨架已完成）

### 执行自然语言意图

```http
POST /intent/execute
Content-Type: application/json

{
  "text": "帮我把美国区 ROI 低于 0.5 的 Campaign 预算降低 20%",
  "dry_run": true
}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| text | string | 自然语言指令 |
| dry_run | bool | 是否仅预览不执行 (默认 true) |

**响应**：
```json
{
  "intent_type": "budget_adjustment",
  "confidence": 0.95,
  "security_level": "L2",
  "requires_approval": true,
  "affected_campaigns": 12,
  "estimated_impact": {
    "daily_spend_reduction": 5000,
    "expected_roi_improvement": 0.15
  },
  "actions": [...]
}
```

### 安全级别说明

| 级别 | 说明 | 执行方式 |
|------|------|---------|
| **L0** | 只读操作 | 自动执行 |
| **L1** | 微调操作 | 一键确认 + 超时自动执行 |
| **L2** | 重大变更 | 需要人工审核 |
| **L3** | 建议类 | 仅生成建议，不执行 |

---

## 前端 API 封装示例

```javascript
// src/api.js

import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器 - 附加 JWT Token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Campaign API 封装
export const campaignAPI = {
  list: (params) => api.get('/campaigns', { params }),
  get: (id) => api.get(`/campaigns/${id}`),
  getAdGroups: (id) => api.get(`/campaigns/${id}/adgroups`),
  getCreatives: (params) => api.get('/creatives', { params })
}

// 数值安全转换工具
export const safeNum = (val, formatter = v => v) => {
  const num = Number(val)
  return isNaN(num) ? null : formatter(num)
}
```

---

## 常见问题 (FAQ)

### Q: 为什么数值是字符串类型？
A: SQLAlchemy 的 `DECIMAL` 类型在 JSON 序列化时默认转为字符串，避免浮点数精度丢失。前端使用 `Number()` 转换后再渲染。

### Q: 如何初始化测试数据？
```bash
cd backend
python init_db.py          # 初始化完整数据库
python init_alerts.py      # 初始化告警数据
python reset_password.py   # 重置管理员密码
```

### Q: 前端请求出现 CORS 错误？
A: Vite 代理配置已在 `vite.config.js` 中配置 `/api` 代理到 `http://localhost:8000`，确保后端服务正常启动。

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-06-28 | 完整API参考文档<br>- Campaign API 嵌套返回<br>- Creative API 完整字段<br>- 告警 API<br>- 前端数值处理最佳实践 |
| v0.1 | 2026-06-27 | 初始版本，连接器系统 |

---

*文档最后更新：2026-06-28*
