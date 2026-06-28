"""
生成 SmartUA 连接器系统的 Mock 数据
包括：凭证配置、同步历史、ODS/DWD/DWS 各层数据
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import date, datetime, timedelta
import random
import hashlib
from decimal import Decimal

from app.db.base import SessionLocal, Base, engine
from app.core.security import get_password_hash
from app.models.sys import User, App, UserAppBinding
from app.models.data import (
    ConnectorCredential, ConnectorRun, RawPayload,
    FactMediaDaily, FactMMPDaily, AggUADaily
)

# 重新创建所有表
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    # ========== 1. 创建基础数据 ==========
    print("Creating users and apps...")

    # 创建用户
    admin = User(
        email='admin@smartua.com',
        username='admin',
        password_hash=get_password_hash('123456'),
        status='active'
    )
    db.add(admin)
    db.flush()

    # 创建应用
    app = App(
        name='Block Blast Demo',
        bundle_id='com.game.blockblast',
        platform='mobile',
        status='active',
        created_by=admin.id
    )
    db.add(app)
    db.flush()

    # 绑定用户和应用
    binding = UserAppBinding(
        user_id=admin.id,
        app_id=app.id,
        role_id=1,
        is_default=True
    )
    db.add(binding)
    db.flush()

    app_id = app.id
    print(f"Created app: id={app_id}")

    # ========== 2. 创建连接器凭证 ==========
    print("Creating connector credentials...")

    platforms = [
        ("meta", "Meta Ads", "oauth2"),
        ("google", "Google Ads", "oauth2"),
        ("appsflyer", "AppsFlyer MMP", "api_key"),
    ]

    credentials = []
    for platform, name, auth_type in platforms:
        cred = ConnectorCredential(
            app_id=app_id,
            platform=platform,
            account_name=f"{name} Production",
            account_id=f"{platform}_acc_{random.randint(10000, 99999)}",
            auth_type=auth_type,
            credentials_json={
                "api_key": f"mock_token_{platform}_{random.randint(1000, 9999)}",
                "app_secret": f"mock_secret_{random.randint(1000, 9999)}"
            },
            sync_frequency="daily",
            auto_sync_enabled=True,
            status="active",
            is_verified=True,
            last_verified_at=datetime.utcnow(),
            notes=f"Mock {name} credential for testing"
        )
        db.add(cred)
        credentials.append(cred)
        print(f"  Created credential: {platform}")

    db.flush()

    # ========== 3. 创建同步历史 ==========
    print("Creating sync runs...")

    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    platforms_for_runs = ["meta", "meta", "meta", "google", "google", "appsflyer"]
    report_types = ["campaign_daily", "adset_daily", "ad_daily"]

    for i, platform in enumerate(platforms_for_runs):
        sync_date = end_date - timedelta(days=i // 2)
        report_type = random.choice(report_types)

        status = random.choices(["success", "success", "success", "failed"], weights=[0.8, 0.8, 0.8, 0.2])[0]
        raw_count = random.randint(50, 500) if status == "success" else 0

        run = ConnectorRun(
            app_id=app_id,
            created_at=datetime(sync_date.year, sync_date.month, sync_date.day,
                              random.randint(2, 5),
                              random.randint(0, 59)),
            connector=platform,
            source_type="media" if platform != "appsflyer" else "mmp",
            operation="pull",
            report_type=report_type if platform != "appsflyer" else "attribution",
            date_from=sync_date - timedelta(days=7),
            date_to=sync_date,
            account_id=f"{platform}_acc_12345",
            currency="USD",
            status=status,
            raw_row_count=raw_count,
            normalized_row_count=raw_count if status == "success" else 0,
            error_detail=None if status == "success" else "API rate limit exceeded",
            executed_by=admin.id
        )
        db.add(run)
        db.flush()

        if status == "success":
            # 为成功的同步创建 ODS 层数据
            raw_payload = RawPayload(
                run_id=run.id,
                app_id=app_id,
                connector=platform,
                source_type="media" if platform != "appsflyer" else "mmp",
                report_type=report_type,
                endpoint=f"reports.{platform}.com/v1",
                account_id=f"{platform}_acc_12345",
                date_from=sync_date - timedelta(days=7),
                date_to=sync_date,
                request_hash=hashlib.md5(f"{platform}_{sync_date}".encode()).hexdigest(),
                payload_hash=hashlib.md5(f"payload_{platform}_{sync_date}".encode()).hexdigest(),
                row_count=raw_count,
                payload_json={
                    "platform": platform,
                    "pulled_at": datetime.utcnow().isoformat(),
                    "rows_count": raw_count,
                    "mock": True
                },
                file_size_bytes=random.randint(10000, 100000)
            )
            db.add(raw_payload)

        print(f"  Created run: {platform} {sync_date} - {status}")

    # ========== 4. 创建 DWD 层媒体事实数据 ==========
    print("Creating DWD media daily data...")

    campaigns = [
        ("US_iOS_Install", "campaign_001"),
        ("US_Android_Install", "campaign_002"),
        ("GB_iOS_ROAS", "campaign_003"),
        ("CA_Android_Event", "campaign_004"),
        ("DE_iOS_Video", "campaign_005"),
    ]

    countries = ["US", "GB", "CA", "AU", "DE", "FR", "JP", "KR"]

    for day_offset in range(30):
        current_date = end_date - timedelta(days=day_offset)

        for platform in ["meta", "google"]:
            for campaign_name, campaign_id in campaigns[:3]:
                for country in countries[:3]:
                    impressions = random.randint(10000, 100000)
                    clicks = random.randint(impressions // 100, impressions // 10)
                    spend = round(random.uniform(100, 5000), 2)
                    installs = random.randint(10, 500)

                    row_hash = hashlib.md5(
                        f"{platform}:{current_date}:{campaign_id}:{country}".encode()
                    ).hexdigest()

                    fact_media = FactMediaDaily(
                        run_id=random.randint(1, 3),
                        app_id=app_id,
                        source_platform=platform,
                        source_type="media",
                        date=current_date,
                        account_id=f"{platform}_acc_12345",
                        app_key="com.game.blockblast",
                        media_source=platform,
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        adset_id=f"adset_{campaign_id}",
                        adset_name=f"Adset - {campaign_name}",
                        ad_id=f"ad_{campaign_id}",
                        ad_name=f"Ad - {campaign_name}",
                        creative_id=f"creative_{random.randint(1, 10)}",
                        creative_name=f"Creative - {campaign_name}",
                        country=country,
                        currency="USD",
                        impressions=impressions,
                        clicks=clicks,
                        spend=Decimal(str(spend)),
                        spend_usd=Decimal(str(spend)),
                        media_installs=installs,
                        media_conversions=random.randint(installs // 4, installs // 2),
                        ctr=Decimal(str(round(clicks / impressions if impressions > 0 else 0, 6))),
                        cpc=Decimal(str(round(spend / clicks if clicks > 0 else 0, 4))),
                        cpm=Decimal(str(round(spend * 1000 / impressions if impressions > 0 else 0, 4))),
                        cpi=Decimal(str(round(spend / installs if installs > 0 else 0, 4))),
                        source_row_hash=row_hash,
                        raw_row_json={"mock": True}
                    )
                    db.add(fact_media)

    print(f"  Created DWD media data for 30 days")

    # ========== 5. 创建 DWD 层 MMP 归因数据 ==========
    print("Creating DWD MMP daily data...")

    for day_offset in range(30):
        current_date = end_date - timedelta(days=day_offset)

        for platform in ["meta", "google", "tiktok"]:
            for campaign_name, campaign_id in campaigns[:3]:
                for country in countries[:3]:
                    installs = random.randint(50, 1000)
                    revenue = round(random.uniform(1000, 20000), 2)
                    cost = round(random.uniform(500, 10000), 2)

                    row_hash = hashlib.md5(
                        f"appsflyer:{current_date}:{campaign_id}:{country}".encode()
                    ).hexdigest()

                    fact_mmp = FactMMPDaily(
                        run_id=random.randint(4, 6),
                        app_id=app_id,
                        mmp="appsflyer",
                        date=current_date,
                        app_key="com.game.blockblast",
                        platform=random.choice(["android", "ios"),
                        media_source=platform,
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        country=country,
                        currency="USD",
                        attributed_installs=installs,
                        registrations=int(installs * random.uniform(0.6, 0.9)),
                        payers=int(installs * random.uniform(0.1, 0.3)),
                        cost=Decimal(str(cost)),
                        cost_usd=Decimal(str(cost)),
                        revenue=Decimal(str(revenue)),
                        revenue_usd=Decimal(str(revenue)),
                        roi_d0=Decimal(str(round(revenue / cost if cost > 0 else 0, 6))),
                        roi_d1=Decimal(str(round(revenue * 1.2 / cost if cost > 0 else 0, 6))),
                        roi_d3=Decimal(str(round(revenue * 1.5 / cost if cost > 0 else 0, 6))),
                        roi_d7=Decimal(str(round(revenue * 2.0 / cost if cost > 0 else 0, 6))),
                        retention_d1=Decimal(str(round(random.uniform(0.3, 0.6), 6))),
                        retention_d3=Decimal(str(round(random.uniform(0.15, 0.35), 6))),
                        retention_d7=Decimal(str(round(random.uniform(0.08, 0.2), 6))),
                        source_row_hash=row_hash,
                        raw_row_json={"mock": True}
                    )
                    db.add(fact_mmp)

    print(f"  Created DWD MMP data for 30 days")

    # ========== 6. 创建 DWS 层聚合数据 ==========
    print("Creating DWS aggregated data...")

    # 先提交 DWD 数据再聚合
    db.commit()

    # 从 DWD 聚合到 DWS
    from sqlalchemy import func, and_

    for day_offset = 0
    current_date = end_date - timedelta(days=day_offset)

    media_agg = db.query(
        FactMediaDaily.date.label("active_date"),
        FactMediaDaily.app_key,
        FactMediaDaily.media_source,
        FactMediaDaily.source_platform,
        FactMediaDaily.country,
        FactMediaDaily.campaign_id,
        FactMediaDaily.campaign_name,
        func.sum(FactMediaDaily.impressions).label("total_shows"),
        func.sum(FactMediaDaily.clicks).label("total_clicks"),
        func.sum(FactMediaDaily.spend).label("total_cost"),
        func.sum(FactMediaDaily.spend_usd).label("total_cost_usd"),
        func.sum(FactMediaDaily.media_installs).label("total_media_installs"),
    ).filter(
        and_(
            FactMediaDaily.app_id == app_id,
            FactMediaDaily.date == current_date
        )
    ).group_by(
        FactMediaDaily.date,
        FactMediaDaily.app_key,
        FactMediaDaily.media_source,
        FactMediaDaily.source_platform,
        FactMediaDaily.country,
        FactMediaDaily.campaign_id,
        FactMediaDaily.campaign_name,
    ).all()

    for row in media_agg:
        mmp_data = db.query(
            func.sum(FactMMPDaily.attributed_installs).label("total_mmp_installs"),
            func.sum(FactMMPDaily.registrations).label("total_registers"),
            func.sum(FactMMPDaily.revenue).label("total_revenue"),
        ).filter(
            and_(
                FactMMPDaily.app_id == app_id,
                FactMMPDaily.date == row.active_date,
                FactMMPDaily.campaign_id == row.campaign_id,
                FactMMPDaily.country == row.country,
            )
        ).first()

        total_shows = row.total_shows or 0
        total_clicks = row.total_clicks or 0
        total_cost = row.total_cost or 0
        total_cost_usd = row.total_cost_usd or 0
        total_media_installs = row.total_media_installs or 0
        total_mmp_installs = mmp_data.total_mmp_installs or 0
        total_registers = mmp_data.total_registers or 0
        total_revenue = mmp_data.total_revenue or 0

        agg = AggUADaily(
            app_id=app_id,
            active_date=row.active_date,
            app_key=row.app_key,
            bundle_name="com.game.blockblast",
            media_source=row.media_source,
            source_platform=row.source_platform,
            country=row.country,
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            match_status="matched" if total_mmp_installs > 0 else "partial",
            signal_confidence="high" if total_mmp_installs > 100 else "medium",
            total_shows=total_shows,
            total_clicks=total_clicks,
            total_cost=total_cost,
            total_cost_usd=total_cost_usd,
            total_registers=total_registers,
            total_media_installs=total_media_installs,
            total_mmp_installs=total_mmp_installs,
            total_revenue=total_revenue,
            total_revenue_usd=total_revenue,
            ctr=Decimal(str(round(total_clicks / total_shows if total_shows > 0 else 0, 6))),
            cpm=Decimal(str(round(total_cost_usd * 1000 / total_shows if total_shows > 0 else 0, 4))),
            cpc=Decimal(str(round(total_cost_usd / total_clicks if total_clicks > 0 else 0, 4))),
            af_cpi=Decimal(str(round(total_cost_usd / total_mmp_installs if total_mmp_installs > 0 else 0, 4))),
            af_cvr=Decimal(str(round(total_registers / total_mmp_installs if total_mmp_installs > 0 else 0, 6))),
            af_arpu=Decimal(str(round(total_revenue / total_mmp_installs if total_mmp_installs > 0 else 0, 4))),
            ipm=Decimal(str(round(total_mmp_installs * 1000 / total_shows if total_shows > 0 else 0, 6))),
            roi_0=Decimal(str(round(total_revenue / total_cost_usd if total_cost_usd > 0 else 0, 6))),
            is_forecast=False
        )
        db.add(agg)

    print(f"  Created DWS aggregated data")

    db.commit()
    print("\n=== Mock data generation completed successfully! ===")
    print(f"\nSummary:")
    print(f"  - Users: 1")
    print(f"  - Apps: 1")
    print(f"  - Connector Credentials: {len(credentials)}")
    print(f"  - Connector Runs: ~6")
    print(f"  - DWD Media Rows: {db.query(FactMediaDaily).count()}")
    print(f"  - DWD MMP Rows: {db.query(FactMMPDaily).count()}")
    print(f"  - DWS Aggregated Rows: {db.query(AggUADaily).count()}")
    print(f"\nYou can now login with: admin@smartua.com / 123456")

except Exception as e:
    db.rollback()
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
