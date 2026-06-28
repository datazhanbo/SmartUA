# SmartUA 外部系统连接器设计文档

---

## 📚 前置知识：1分钟理解 UA 数据链路

### 什么是 UA？
**User Acquisition (用户获取)** - 在游戏/App行业，指花钱买用户的过程，俗称"买量"。

### 为什么需要连接器？
```
投放操作 → 花钱买量 → 产生花费数据 (媒体平台)
                    ↓
用户安装 → 产生行为 → 归因到具体渠道 (MMP平台)
                    ↓
                  ROI 计算 (花了多少钱，赚了多少钱)
```

**没有连接器 = 数据分散在各个平台，没法算 ROI，瞎投钱。**

### 核心概念速查表

| 术语 | 大白话 | 例子 |
|------|--------|------|
| **Media** | 广告平台 | Meta, Google, TikTok |
| **MMP** | 归因平台 | AppsFlyer, Adjust (追踪用户从哪个广告来的) |
| **ODS** | 原始数据仓库 | API 拉回来啥就存啥，不改一字 |
| **DWD** | 洗干净的数据 | 统一字段名，去重 |
| **DWS** | 算好的指标 | ROI, CPI, CTR 都算好了 |
| **ADS** | 直接能用的 | Dashboard 直接展示 |
| **幂等性** | 拉多少次结果都一样 | 重复拉取不产生重复数据 |
| **source_row_hash** | 数据身份证 | 每行的唯一指纹，用来去重 |

---

## 🎯 设计原则

> **外部系统对接是 UA 平台最重要的数据基础**
>
> 所有投放优化、ROI分析、自动化决策都依赖于准确、完整、及时的数据接入

### 核心设计原则

1. **平台无关抽象层** - 统一的数据模型，屏蔽媒体差异
2. **完整溯源能力** - ODS层100%保留原始响应，支持数据重放
3. **幂等性保证** - 重复拉取不产生重复数据
4. **可观测性** - 每一次同步都有完整的运行记录
5. **容错性** - 单平台故障不影响其他平台同步

---

## 🏗️ 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     外部系统 API 层                                │
├─────────┬─────────┬──────────┬────────────┬──────────────────┤
│  Meta   │ Google  │  TikTok  │ AppsFlyer  │   ... 更多        │
└─────────┴─────────┴──────────┴────────────┴──────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Connector 抽象层                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  BaseConnector 基类                                        │  │
│  │  - auth()          # 认证                                 │  │
│  │  - pull()          # 拉取数据                             │  │
│  │  - normalize()     # 字段标准化                           │  │
│  │  - validate()      # 数据校验                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│         ▲              ▲              ▲                          │
│         │              │              │                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                   │
│  │MetaConnector│ │GoogleConn  │ │TikTokConn  │  ... 实现类       │
│  └────────────┘ └────────────┘ └────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     四层数据仓库                                  │
│  ODS → raw_payloads (原始响应 1:1 保存)                         │
│       → connector_runs (同步运行记录)                           │
│                                                                   │
│  DWD → fact_media_daily (媒体事实表)                             │
│      → fact_mmp_daily   (归因事实表)                            │
│                                                                   │
│  DWS → agg_ua_daily (ROI360 聚合宽表)                            │
│                                                                   │
│  ADS → campaign_health / alerts / dashboard_cache                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 connector_runs 表设计详解

### 表结构说明

| 字段 | 类型 | 说明 | 设计目的 |
|------|------|------|---------|
| `id` | PK | 主键 | |
| `app_id` | FK | 租户隔离 | 多租户数据隔离 |
| `created_at` | DateTime | 同步开始时间 | 可观测性 |
| **`connector`** | String(32) | 连接器类型 | `meta` / `google` / `tiktok` / `appsflyer` / `adjust` |
| **`source_type`** | String(32) | 数据源类型 | `media` / `mmp` / `dsp` 三类 |
| **`operation`** | String(32) | 操作类型 | `pull`(拉取) / `push`(回传) / `sync`(双向) |
| **`report_type`** | String(32) | 报表类型 | 见下方枚举 |
| `date_from` | Date | 数据起始日期 | 时间窗口 |
| `date_to` | Date | 数据结束日期 | 时间窗口 |
| `account_id` | String(64) | 广告账号 ID | 多账号支持 |
| `app_key` | String(64) | 应用标识 | MMP 端应用 |
| `currency` | String(8) | 原始货币 | 汇率转换溯源 |
| `params_json` | JSON | 原始请求参数 | 重试/排障用 |
| **`status`** | String(16) | 运行状态 | `running` / `success` / `failed` / `partial` |
| `raw_row_count` | Int | 原始行数 | ODS层统计 |
| `normalized_row_count` | Int | 标准化行数 | DWD层统计 |
| `error_detail` | Text | 错误详情 | 排障用 |
| `adapter_response_json` | JSON | 适配器响应头 | 速率限制、分页等元数据 |
| `executed_by` | FK | 触发人 | 手动/自动区分 |

### report_type 枚举值

| 类型 | 说明 | 适用平台 |
|------|------|---------|
| `campaign_daily` | Campaign 日报表 | 所有媒体 |
| `adset_daily` | AdSet 日报表 | 所有媒体 |
| `ad_daily` | Ad 日报表 | 所有媒体 |
| `creative_daily` | 素材维度报表 | Meta / TikTok |
| `installs_raw` | 安装原始数据 | MMP |
| `in_app_events` | 内购事件原始数据 | MMP |
| `attribution` | 归因结果数据 | MMP |

---

## 🧩 连接器基类设计

### BaseConnector 接口定义

```python
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Dict, Optional

class BaseConnector(ABC):
    """所有连接器的基类"""

    # 子类必须实现
    platform: str           # 平台标识，如 "meta", "google"
    source_type: str        # "media" / "mmp" / "dsp"
    rate_limit: int         # API 每秒请求限制

    @abstractmethod
    def auth(self) -> bool:
        """
        认证方法
        - OAuth2 (Meta/Google)
        - API Key (TikTok/AppsFlyer)
        - Service Account (Google)
        """
        pass

    @abstractmethod
    def pull(self,
             date_from: date,
             date_to: date,
             report_type: str,
             **kwargs) -> Dict[str, Any]:
        """
        拉取数据核心方法

        返回格式:
        {
            "raw_rows": [...],          # 原始行数据列表
            "metadata": {
                "total_rows": int,      # 总行数
                "currency": str,        # 货币
                "is_complete": bool,    # 是否完整拉取
                "rate_limit_remaining": int,  # 剩余配额
                "next_page_token": str,       # 分页标记
            }
        }
        """
        pass

    @abstractmethod
    def normalize(self, raw_rows: List[Dict]) -> List[Dict]:
        """
        字段标准化转换
        将各媒体不同命名字段统一为 SmartUA 标准字段
        """
        pass

    def validate(self, rows: List[Dict]) -> bool:
        """
        数据校验（可选重写）
        - 必填字段检查
        - 数值合理性检查
        - 幂等性校验
        """
        return True

    def save_ods(self, raw_data: Dict, run_id: int) -> int:
        """
        保存原始数据到 ODS 层（统一实现）
        返回保存的行数
        """
        pass

    def save_dwd(self, normalized_rows: List[Dict], run_id: int) -> int:
        """
        保存标准化数据到 DWD 层（统一实现）
        返回保存的行数
        """
        pass
```

---

## 🔄 跨媒体字段标准化映射

### 核心指标映射表

| SmartUA 标准字段 | Meta 字段 | Google Ads 字段 | TikTok 字段 | 单位统一 |
|-----------------|-----------|----------------|------------|---------|
| `campaign_id` | `campaign_id` | `campaign.id` | `campaign_id` | 字符串化 |
| `campaign_name` | `campaign_name` | `campaign.name` | `campaign_name` | UTF-8 |
| `adset_id` | `adset_id` | `ad_group.id` | `adgroup_id` | 字符串化 |
| `ad_id` | `ad_id` | `ad.id` | `ad_id` | 字符串化 |
| `impressions` | `impressions` | `metrics.impressions` | `impressions` | 整数 |
| `clicks` | `clicks` | `metrics.clicks` | `clicks` | 整数 |
| `spend` | `spend` | `metrics.cost_micros / 1e6` | `spend` | 原币 |
| `spend_usd` | `spend * rate` | `cost * rate` | `spend * rate` | 美元 |
| `ctr` | `ctr` | `metrics.ctr` | `ctr` | 小数 (0-1) |
| `cpc` | `cpc` | `metrics.average_cpc` | `cpc` | 美元 |
| `cpm` | `cpm` | `metrics.average_cpm` | `cpm` | 美元 |
| `media_installs` | `mobile_app_installs` | `metrics.installs` | `installs` | 整数 |
| `conversions` | `conversions` | `metrics.conversions` | `conversions` | 整数 |
| `date` | `date_start` | `segments.date` | `dimensions.stat_time_day` | YYYY-MM-DD |
| `country` | `country` | `segments.country_criterion_id` → 映射 | `country_code` | ISO 3166 |

### 特殊字段说明

1. **`source_row_hash`** - 幂等性保证
   ```python
   # 每行数据生成唯一哈希
   source_row_hash = md5(f"{platform}:{date}:{campaign_id}:{ad_id}:{country}").hexdigest()
   # 数据库唯一约束，重复自动跳过
   ```

2. **`raw_row_json`** - 安全网
   - 标准化过程中丢弃的字段全部保留在 JSON
   - 后续发现字段缺失可回查重算
   - 占存储空间换数据完整性

---

## 📊 媒体平台对接矩阵

### 已规划支持的平台

| 平台 | 类型 | 认证方式 | 数据延迟 | 速率限制 | 优先级 |
|------|------|---------|---------|---------|-------|
| Meta Ads | Media | OAuth 2.0 | 4小时 | 200 req/h | P0 |
| Google Ads | Media | OAuth 2.0 | 4小时 | 1000 req/h | P0 |
| TikTok Ads | Media | API Key | 6小时 | 100 req/h | P0 |
| AppsFlyer | MMP | API Key | 4小时 | 200 req/h | P0 |
| Adjust | MMP | API Key | 6小时 | 100 req/h | P1 |
| Apple Search Ads | Media | API Key | 4小时 | 200 req/h | P1 |
| Unity Ads | Media | API Key | 12小时 | 100 req/h | P2 |
| IronSource | Mediation | API Key | 6小时 | 100 req/h | P2 |

### 关键差异点处理

| 差异点 | Meta | Google | TikTok | 统一方案 |
|--------|------|--------|--------|---------|
| 时区 | 广告账户时区 | 账户时区 | UTC+0 | 拉取时统一转 UTC |
| 货币 | 多货币 | 多货币 | 多货币 | DWD 层统一转 USD |
| 安装定义 | 媒体归因 | Google 归因 | 媒体归因 | 与 MMP 对齐 |
| 分页 | Cursor | Page Token | Offset | 抽象为 next_page_token |
| 归因窗口 | 可配置 | 可配置 | 固定 | params_json 保存配置 |

---

## 🔌 同步流程设计

### 标准同步 Pipeline

```
1. 调度触发
   ├─ 定时任务 (APScheduler)
   └─ 手动触发 (API)

2. 创建 ConnectorRun 记录
   ├─ status = "running"
   ├─ 记录所有参数
   └─ 分配 run_id

3. 认证 + 拉取
   ├─ 调用具体平台 auth()
   ├─ 循环分页 pull()
   │   └─ 每批数据立即写入 raw_payloads
   └─ 速率限制自动等待

4. 标准化 + 写入 DWD
   ├─ normalize() 字段映射
   ├─ validate() 数据校验
   ├─ 计算 source_row_hash
   └─ 幂等写入 fact_media_daily (ON CONFLICT DO NOTHING)

5. 聚合到 DWS
   ├─ 按天增量聚合
   └─ 更新 agg_ua_daily

6. 更新 ConnectorRun 状态
   ├─ status = "success" / "failed"
   ├─ raw_row_count / normalized_row_count
   └─ 如有异常写入 error_detail
```

### 故障恢复机制

1. **断点续传** - 已拉取的 page 不重复拉取，next_page_token 持久化
2. **幂等写入** - source_row_hash 唯一约束，重复拉取不脏数据
3. **数据重放** - 只要 ODS 层完整，可随时从 raw_payloads 重跑 DWD/DWS
4. **自动重试** - 网络失败指数退避重试（最多 5 次）

---

## 📈 可观测性

### 每一次同步都可追溯

```sql
-- 查看最近 7 天各平台同步情况
SELECT
  connector,
  DATE(created_at) as dt,
  COUNT(*) as sync_times,
  SUM(raw_row_count) as total_rows,
  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*) as success_rate
FROM connector_runs
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 2 DESC, 1;
```

### 数据质量监控指标

| 监控指标 | 告警阈值 | 说明 |
|---------|---------|------|
| 同步成功率 | < 95% | 平台可能故障 |
| 行数波动率 | ±30% | 数据可能缺失 |
| 零花费检测 | 连续 3 天 0 | 账号权限可能失效 |
| ROI 波动率 | ±50% | 数据口径可能变更 |

---

## 🚀 扩展能力

### 自定义连接器插件

用户可以通过实现 BaseConnector 扩展新平台：

```python
# my_custom_connector.py
class MyCustomConnector(BaseConnector):
    platform = "my_dsp"
    source_type = "dsp"
    rate_limit = 50

    def auth(self):
        # 你的认证逻辑
        pass

    def pull(self, date_from, date_to, report_type, **kwargs):
        # 你的拉取逻辑
        pass

    def normalize(self, raw_rows):
        # 你的标准化逻辑
        pass
```

注册插件后自动可用，无需修改核心代码。

---

## 📝 实施路线图

| 阶段 | 内容 | 预计工作量 |
|------|------|-----------|
| **Phase 1** | BaseConnector 基类实现 + Meta 连接器 | 2周 |
| **Phase 2** | Google + TikTok 连接器 | 2周 |
| **Phase 3** | AppsFlyer MMP 连接器 + 归因对齐 | 2周 |
| **Phase 4** | 调度系统 + 数据质量监控 | 1周 |
| **Phase 5** | 插件化架构 + 自定义连接器 | 1周 |

---

## 🔗 相关文档索引

- [ARCHITECTURE.md](./ARCHITECTURE.md) - 四层数据仓库总览
- [LLM_ROUTING.md](./LLM_ROUTING.md) - LLM 路由设计
- [USER_MANUAL.md](./USER_MANUAL.md) - 用户操作手册

---

*Last updated: 2026-06-27*
