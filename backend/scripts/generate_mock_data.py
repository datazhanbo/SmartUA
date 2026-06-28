#!/usr/bin/env python3
"""
Mock数据生成器
生成完整的四层数据：ODS -> DWD -> DWS -> ADS
支持多App、多媒体平台、多国家
包含植入的异常点，用于演示异常检测能力
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.base import engine
from app.models.sys import App, User, Role, Permission, UserAppBinding, user_roles
from app.models.data import (
    ConnectorRun, RawPayload, FactMediaDaily, FactMMPDaily,
    AggUADaily, CampaignHealth, Alert, DashboardCache
)
from app.models.intent import IntentExecution, StrategyTemplate, ActionLog
from app.core.security import get_password_hash

# ==================== 配置 ====================
MOCK_CONFIG = {
    "apps": [
        {
            "app_key": "com.block.juggle",
            "app_name": "Block Blast",
            "base_cpi_usd": 1.2,
            "base_roi_d7": 1.15,
            "retention_d1": 0.42,
            "countries": ["US", "JP", "GB", "DE", "CA", "BR"],
            "media_sources": [
                {"name": "Meta Ads", "platform": "meta", "weight": 0.4},
                {"name": "Google Ads", "platform": "google", "weight": 0.35},
                {"name": "TikTok Ads", "platform": "tiktok", "weight": 0.15},
                {"name": "AppLovin", "platform": "applovin", "weight": 0.1},
            ],
            "campaign_count": 15,
            "daily_spend_range": [500, 8000],
        },
        {
            "app_key": "com.hungry.mahjong",
            "app_name": "Mahjong Master",
            "base_cpi_usd": 2.5,
            "base_roi_d7": 0.95,
            "retention_d1": 0.35,
            "countries": ["US", "JP", "TW", "KR", "SG"],
            "media_sources": [
                {"name": "Meta Ads", "platform": "meta", "weight": 0.5},
                {"name": "Google Ads", "platform": "google", "weight": 0.35},
                {"name": "TikTok Ads", "platform": "tiktok", "weight": 0.15},
            ],
            "campaign_count": 10,
            "daily_spend_range": [300, 5000],
        }
    ],
    "days": 30,
    "anomalies": [
        {
            "app_idx": 0,
            "date_offset": -3,  # 3天前
            "campaign_idx": 2,
            "type": "roi_drop",
            "severity": 0.4,   # ROI下降到正常的40%
            "description": "ROI异常下降 - 素材疲劳"
        },
        {
            "app_idx": 0,
            "date_offset": -5,
            "campaign_idx": 5,
            "type": "cpi_spike",
            "severity": 3.0,   # CPI涨到正常的3倍
            "description": "CPI异常上涨 - 竞价竞争加剧"
        },
        {
            "app_idx": 1,
            "date_offset": -2,
            "campaign_idx": 3,
            "type": "spend_drop",
            "severity": 0.2,   # 花费只剩正常的20%
            "description": "花费突然下降 - 账户问题"
        }
    ],
    "users": [
        {
            "email": "admin@smartua.com",
            "username": "Admin User",
            "password": "admin123",
            "role": "admin",
            "department": "Technology"
        },
        {
            "email": "optimizer1@smartua.com",
            "username": "张三（优化师）",
            "password": "opt123",
            "role": "optimizer",
            "department": "UA Team"
        },
        {
            "email": "analyst1@smartua.com",
            "username": "李四（分析师）",
            "password": "ana123",
            "role": "analyst",
            "department": "Analytics"
        },
        {
            "email": "finance@smartua.com",
            "username": "王五（财务）",
            "password": "fin123",
            "role": "finance",
            "department": "Finance"
        }
    ]
}

# 预定义角色和权限
ROLES = [
    {"name": "admin", "label": "管理员", "is_system": True,
     "description": "系统管理员，拥有所有权限"},
    {"name": "optimizer", "label": "优化师", "is_system": True,
     "description": "投放优化师，可以执行调整操作"},
    {"name": "analyst", "label": "分析师", "is_system": True,
     "description": "数据分析师，只读权限"},
    {"name": "finance", "label": "财务", "is_system": True,
     "description": "财务人员，对账相关权限"},
    {"name": "readonly", "label": "只读用户", "is_system": True,
     "description": "只读访问权限"},
]

PERMISSIONS = [
    # App管理
    {"code": "app:read", "name": "查看App", "module": "app", "action": "read"},
    {"code": "app:write", "name": "编辑App", "module": "app", "action": "write"},
    {"code": "app:create", "name": "创建App", "module": "app", "action": "create"},

    # 数据查看
    {"code": "data:read", "name": "查看数据", "module": "data", "action": "read"},
    {"code": "data:export", "name": "导出数据", "module": "data", "action": "export"},

    # Campaign操作
    {"code": "campaign:read", "name": "查看Campaign", "module": "campaign", "action": "read"},
    {"code": "campaign:write", "name": "调整Campaign", "module": "campaign", "action": "write"},
    {"code": "campaign:create", "name": "创建Campaign", "module": "campaign", "action": "create"},

    # 告警
    {"code": "alert:read", "name": "查看告警", "module": "alert", "action": "read"},
    {"code": "alert:write", "name": "处理告警", "module": "alert", "action": "write"},

    # 财务
    {"code": "finance:read", "name": "查看财务", "module": "finance", "action": "read"},
    {"code": "finance:reconcile", "name": "执行对账", "module": "finance", "action": "execute"},

    # 系统
    {"code": "system:admin", "name": "系统管理", "module": "system", "action": "admin"},
]

# 角色-权限映射
ROLE_PERMISSIONS = {
    "admin": ["app:read", "app:write", "app:create",
              "data:read", "data:export",
              "campaign:read", "campaign:write", "campaign:create",
              "alert:read", "alert:write",
              "finance:read", "finance:reconcile",
              "system:admin"],
    "optimizer": ["app:read",
                  "data:read", "data:export",
                  "campaign:read", "campaign:write",
                  "alert:read", "alert:write"],
    "analyst": ["app:read",
                "data:read", "data:export",
                "campaign:read",
                "alert:read"],
    "finance": ["app:read",
                "data:read",
                "finance:read", "finance:reconcile"],
    "readonly": ["app:read", "data:read", "campaign:read"]
}

CAMPAIGN_NAMES = [
    "US-{platform}-Prospecting-V{v}",
    "US-{platform}-Retargeting-V{v}",
    "{country}-{platform}-Broad-V{v}",
    "{country}-{platform}-Lookalike-V{v}",
    "{country}-{platform}-Interest-V{v}",
]


# ==================== 生成函数 ====================

def random_normal(base: float, std_dev: float) -> float:
    """正态分布随机数"""
    return max(0.01, base + random.gauss(0, std_dev * base))


def generate_daily_data(app_config: dict, app_id: int, campaign_id: str,
                         platform: str, country: str, d: date,
                         is_anomaly: bool = False, anomaly_type: str = None, severity: float = None):
    """生成单日数据"""
    base_spend = random.uniform(*app_config["daily_spend_range"]) / len(app_config["countries"])

    # 基础指标
    cpi = random_normal(app_config["base_cpi_usd"], 0.15)
    roi_7 = random_normal(app_config["base_roi_d7"], 0.2)
    retention_7 = random_normal(app_config["retention_d1"] * 0.7, 0.1)

    # 应用异常
    if is_anomaly:
        if anomaly_type == "roi_drop":
            roi_7 = roi_7 * severity
        elif anomaly_type == "cpi_spike":
            cpi = cpi * severity
        elif anomaly_type == "spend_drop":
            base_spend = base_spend * severity

    # 计算派生指标
    installs = int(base_spend / cpi)
    spend = installs * cpi
    revenue = spend * roi_7
    clicks = int(installs / random_normal(0.3, 0.1))
    impressions = int(clicks / random_normal(0.02, 0.2))

    return {
        "date": d,
        "media_source": platform,
        "country": country,
        "campaign_id": campaign_id,
        "campaign_name": campaign_id.replace("_", " ").title(),
        "impressions": impressions,
        "clicks": clicks,
        "spend_usd": spend,
        "installs": installs,
        "cpi": cpi,
        "revenue_usd": revenue,
        "roi_7": roi_7,
        "retention_7": retention_7,
    }


def create_system_data(db: Session):
    """创建系统基础数据（角色、权限、用户、App）"""
    print("Creating system data...")

    # 创建权限
    perm_map = {}
    for p_data in PERMISSIONS:
        perm = Permission(**p_data)
        db.add(perm)
        db.flush()
        perm_map[p_data["code"]] = perm

    # 创建角色
    role_map = {}
    for r_data in ROLES:
        role = Role(**r_data)
        db.add(role)
        db.flush()
        role_map[r_data["name"]] = role

        # 关联权限
        perm_codes = ROLE_PERMISSIONS.get(r_data["name"], [])
        for code in perm_codes:
            if code in perm_map:
                role.permissions.append(perm_map[code])

    # 创建App
    app_map = {}
    for app_config in MOCK_CONFIG["apps"]:
        app = App(
            app_key=app_config["app_key"],
            app_name=app_config["app_name"],
            app_type="game",
            timezone="Asia/Shanghai",
            currency="USD",
            status="active"
        )
        db.add(app)
        db.flush()
        app_map[app_config["app_key"]] = app
        print(f"  Created App: {app.app_name} (ID: {app.id})")

    # 创建用户
    for u_data in MOCK_CONFIG["users"]:
        user = User(
            email=u_data["email"],
            username=u_data["username"],
            password_hash=get_password_hash(u_data["password"]),
            department=u_data["department"],
            status="active"
        )
        # 分配角色
        role = role_map.get(u_data["role"])
        if role:
            user.roles.append(role)

        db.add(user)
        db.flush()
        print(f"  Created User: {user.username} ({user.email})")

        # 绑定到所有App
        for app in app_map.values():
            binding = UserAppBinding(
                user_id=user.id,
                app_id=app.id,
                role_id=role.id,
                is_default=(app == list(app_map.values())[0])
            )
            db.add(binding)

    db.commit()
    return app_map


def create_ad_data(db: Session, app_map: dict):
    """生成广告数据（DWD + DWS层）"""
    print("\nCreating ad data...")

    end_date = date.today()
    days = MOCK_CONFIG["days"]

    for app_idx, (app_key, app) in enumerate(app_map.items()):
        app_config = MOCK_CONFIG["apps"][app_idx]
        print(f"  Generating data for {app.app_name}...")

        # 生成Campaign
        campaigns = []
        for i in range(app_config["campaign_count"]):
            media = random.choice(app_config["media_sources"])
            country = random.choice(app_config["countries"])
            v = i + 1
            name_tmpl = random.choice(CAMPAIGN_NAMES)
            camp_name = name_tmpl.format(platform=media["platform"], country=country, v=v)
            campaigns.append({
                "id": f"camp_{app.id}_{i+1:03d}",
                "name": camp_name,
                "platform": media["platform"],
                "media_source": media["name"],
                "country": country,
            })

        # 按天生成数据
        for day_offset in range(days):
            d = end_date - timedelta(days=days - day_offset - 1)

            for camp_idx, camp in enumerate(campaigns):
                # 检查是否是异常点
                is_anomaly = False
                anomaly_type = None
                severity = None
                for anom in MOCK_CONFIG["anomalies"]:
                    if (anom["app_idx"] == app_idx and
                        anom["date_offset"] == -(days - day_offset - 1) and
                        anom["campaign_idx"] == camp_idx):
                        is_anomaly = True
                        anomaly_type = anom["type"]
                        severity = anom["severity"]
                        print(f"    ⚠️  Injecting anomaly: {anom['description']}")
                        break

                # 生成数据
                data = generate_daily_data(
                    app_config, app.id, camp["id"],
                    camp["platform"], camp["country"], d,
                    is_anomaly, anomaly_type, severity
                )

                # Media事实表
                media_row = FactMediaDaily(
                    app_id=app.id,
                    source_platform=data["media_source"],
                    source_type="media_bm",
                    date=d,
                    media_source=data["media_source"],
                    campaign_id=data["campaign_id"],
                    campaign_name=data["campaign_name"],
                    country=data["country"],
                    impressions=data["impressions"],
                    clicks=data["clicks"],
                    spend=data["spend_usd"],
                    spend_usd=data["spend_usd"],
                    media_installs=data["installs"],
                    cpi=data["cpi"],
                    ctr=Decimal(data["clicks"]) / Decimal(data["impressions"]) if data["impressions"] > 0 else 0,
                    source_row_hash=f"media_{app.id}_{d}_{camp['id']}",
                )
                db.add(media_row)

                # MMP事实表（90%概率匹配，模拟归因延迟）
                if random.random() < 0.9:
                    mmp_installs = int(data["installs"] * random_normal(0.95, 0.05))
                    mmp_revenue = data["revenue_usd"] * random_normal(1.0, 0.03)
                    mmp_row = FactMMPDaily(
                        app_id=app.id,
                        mmp="appsflyer",
                        date=d,
                        app_key=app_key,
                        media_source=data["media_source"],
                        campaign_id=data["campaign_id"],
                        campaign_name=data["campaign_name"],
                        country=data["country"],
                        attributed_installs=mmp_installs,
                        registrations=int(mmp_installs * random_normal(0.85, 0.05)),
                        cost=data["spend_usd"],
                        cost_usd=data["spend_usd"],
                        revenue=mmp_revenue,
                        revenue_usd=mmp_revenue,
                        roi_d7=data["roi_7"],
                        retention_d7=data["retention_7"],
                        source_row_hash=f"mmp_{app.id}_{d}_{camp['id']}",
                    )
                    db.add(mmp_row)

                # DWS聚合表
                agg_row = AggUADaily(
                    app_id=app.id,
                    active_date=d,
                    app_key=app_key,
                    media_source=data["media_source"],
                    source_platform=data["media_source"],
                    country=data["country"],
                    campaign_id=data["campaign_id"],
                    campaign_name=data["campaign_name"],
                    match_status="matched" if random.random() < 0.85 else "media_only",
                    total_shows=data["impressions"],
                    total_clicks=data["clicks"],
                    total_cost=data["spend_usd"],
                    total_cost_usd=data["spend_usd"],
                    total_registers=int(data["installs"] * 0.85),
                    total_media_installs=data["installs"],
                    total_mmp_installs=int(data["installs"] * 0.9),
                    total_revenue=data["revenue_usd"],
                    total_revenue_usd=data["revenue_usd"],
                    af_cpi=data["cpi"],
                    roi_7=data["roi_7"],
                    retention_7=data["retention_7"],
                )
                db.add(agg_row)

        db.commit()


def create_health_and_alerts(db: Session, app_map: dict):
    """生成Campaign健康度和告警数据"""
    print("\nCreating campaign health scores and alerts...")

    for app in app_map.values():
        # 计算最近7天健康度
        rows = db.query(
            AggUADaily.campaign_id,
            AggUADaily.campaign_name,
            AggUADaily.media_source,
            func.avg(AggUADaily.roi_7).label("avg_roi"),
            func.avg(AggUADaily.af_cpi).label("avg_cpi"),
            func.sum(AggUADaily.total_cost_usd).label("total_spend")
        ).filter(
            AggUADaily.app_id == app.id,
            AggUADaily.active_date >= date.today() - timedelta(days=7)
        ).group_by(
            AggUADaily.campaign_id,
            AggUADaily.campaign_name,
            AggUADaily.media_source
        ).all()

        alerts_created = 0
        for row in rows:
            roi = float(row.avg_roi or 0)
            cpi = float(row.avg_cpi or 0)

            # 计算健康度分数 (0-100)
            roi_score = min(100, max(0, (roi / 1.5) * 100))
            cpi_score = min(100, max(0, (5 / cpi) * 100)) if cpi > 0 else 50
            health_score = int((roi_score * 0.6) + (cpi_score * 0.4))

            if health_score >= 70:
                health_level = "healthy"
                suggestion = "表现良好，考虑加量"
                alert_level = "none"
            elif health_score >= 40:
                health_level = "subhealthy"
                suggestion = "需要关注，考虑优化素材或定向"
                alert_level = "info"
            else:
                health_level = "unhealthy"
                suggestion = "表现较差，建议暂停或大幅调整"
                alert_level = "warning"

            # 健康度记录
            health = CampaignHealth(
                app_id=app.id,
                snapshot_date=date.today(),
                campaign_id=row.campaign_id,
                campaign_name=row.campaign_name,
                media_source=row.media_source,
                health_score=health_score,
                health_level=health_level,
                roi_d7=roi,
                cpi_d7=cpi,
                daily_spend=float(row.total_spend or 0) / 7,
                suggestion=suggestion,
                alert_level=alert_level
            )
            db.add(health)

            # 异常Campaign生成告警
            if health_level == "unhealthy" and alerts_created < 5:
                alert = Alert(
                    app_id=app.id,
                    alert_type="roi_anomaly",
                    severity="warning" if health_score >= 30 else "critical",
                    status="open",
                    campaign_id=row.campaign_id,
                    campaign_name=row.campaign_name,
                    media_source=row.media_source,
                    metric_name="roi_7",
                    metric_value=roi,
                    threshold_value=0.7,
                    baseline_value=1.1,
                    change_percent=(roi - 1.1) / 1.1 * 100 if 1.1 > 0 else 0,
                    description=f"Campaign ROI持续低于阈值，当前值{roi:.2f}",
                    suggested_action={
                        "action": "pause_and_review",
                        "message": "建议暂停投放并检查素材、定向、出价设置"
                    }
                )
                db.add(alert)
                alerts_created += 1

    db.commit()


def create_strategies(db: Session, app_map: dict):
    """创建策略模板"""
    print("\nCreating strategy templates...")

    strategies = [
        {
            "name": "暂停低ROI Campaign",
            "description": "自动暂停ROI低于0.5的Campaign",
            "category": "budget",
            "risk_level": "L1",
            "rules_json": {
                "conditions": [{"metric": "roi_7", "operator": "<", "value": 0.5}],
                "actions": [{"type": "pause_campaign"}],
                "auto_execute": False
            }
        },
        {
            "name": "高ROI自动加量",
            "description": "ROI>1.3且CPI稳定的Campaign自动提升20%预算",
            "category": "budget",
            "risk_level": "L1",
            "rules_json": {
                "conditions": [
                    {"metric": "roi_7", "operator": ">", "value": 1.3},
                    {"metric": "cpi_trend_3d", "operator": "<", "value": 0.1}
                ],
                "actions": [{"type": "increase_budget", "percent": 20}],
                "auto_execute": False
            }
        },
        {
            "name": "素材疲劳轮换",
            "description": "CTR连续3天下降的Campaign自动轮换素材",
            "category": "creative",
            "risk_level": "L0",
            "rules_json": {
                "conditions": [{"metric": "ctr_trend_3d", "operator": "<", "value": -0.15}],
                "actions": [{"type": "rotate_creative"}],
                "auto_execute": True
            }
        }
    ]

    for app in app_map.values():
        admin_user = db.query(User).filter(User.email == "admin@smartua.com").first()
        for s in strategies:
            strategy = StrategyTemplate(
                app_id=app.id,
                created_by=admin_user.id if admin_user else None,
                **s
            )
            db.add(strategy)

    db.commit()


def create_dashboard_cache(db: Session, app_map: dict):
    """创建Dashboard缓存"""
    print("\nCreating dashboard cache...")
    for app in app_map.values():
        # 计算汇总数据
        summary = db.query(
            func.sum(AggUADaily.total_cost_usd).label("spend"),
            func.sum(AggUADaily.total_mmp_installs).label("installs"),
            func.avg(AggUADaily.af_cpi).label("cpi"),
            func.avg(AggUADaily.roi_7).label("roi"),
            func.sum(AggUADaily.total_revenue_usd).label("revenue")
        ).filter(
            AggUADaily.app_id == app.id,
            AggUADaily.active_date >= date.today() - timedelta(days=7)
        ).first()

        cache = DashboardCache(
            app_id=app.id,
            cache_key=f"overview_7d_{app.id}",
            data_json={
                "spend_7d": float(summary.spend or 0),
                "installs_7d": int(summary.installs or 0),
                "avg_cpi_7d": float(summary.cpi or 0),
                "avg_roi_7d": float(summary.roi or 0),
                "revenue_7d": float(summary.revenue or 0),
                "updated_at": datetime.now().isoformat()
            },
            expires_at=datetime.now() + timedelta(hours=1)
        )
        db.add(cache)

    db.commit()


def main():
    print("=" * 60)
    print("SmartUA Mock Data Generator")
    print("=" * 60)

    # 先创建所有表
    print("\nCreating database tables...")
    from app.db.base import Base
    Base.metadata.create_all(bind=engine)

    # 清理现有数据
    print("\n⚠️  This will CLEAR ALL existing data! Press Ctrl+C to abort.")
    print("Waiting 3 seconds...")
    import time
    time.sleep(3)

    with Session(engine) as db:
        # 清理现有数据（按依赖顺序）
        print("\nClearing existing data...")
        db.query(DashboardCache).delete()
        db.query(Alert).delete()
        db.query(CampaignHealth).delete()
        db.query(AggUADaily).delete()
        db.query(FactMMPDaily).delete()
        db.query(FactMediaDaily).delete()
        db.query(RawPayload).delete()
        db.query(ConnectorRun).delete()
        db.query(ActionLog).delete()
        db.query(IntentExecution).delete()
        db.query(StrategyTemplate).delete()
        db.query(UserAppBinding).delete()
        db.query(user_roles).delete()
        db.query(Permission).delete()
        db.query(Role).delete()
        db.query(User).delete()
        db.query(App).delete()
        db.commit()

        # 创建系统数据
        app_map = create_system_data(db)

        # 创建广告数据
        create_ad_data(db, app_map)

        # 创建健康度和告警
        create_health_and_alerts(db, app_map)

        # 创建策略模板
        create_strategies(db, app_map)

        # 创建Dashboard缓存
        create_dashboard_cache(db, app_map)

        print("\n" + "=" * 60)
        print("✅ Mock data generation completed!")
        print(f"   Apps: {len(app_map)}")
        print(f"   Days: {MOCK_CONFIG['days']}")
        print(f"   Users: {len(MOCK_CONFIG['users'])}")
        print("\nLogin credentials:")
        for u in MOCK_CONFIG["users"]:
            print(f"   {u['email']} / {u['password']} ({u['role']})")
        print("=" * 60)


if __name__ == "__main__":
    main()
