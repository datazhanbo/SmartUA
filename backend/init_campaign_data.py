"""
初始化 Campaign / AdGroup / Ad / Creative 数据
将前端 Mock 数据同步到数据库，实现数据持久化
"""
import sys
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, '.')

from app.db.base import SessionLocal
from app.models.campaign import Campaign, AdGroup, Ad, Creative
from app.models.data import Alert
from app.models.sys import App


def init_demo_data():
    db = SessionLocal()

    try:
        # 检查是否已有数据
        campaign_count = db.query(Campaign).count()
        if campaign_count > 0:
            print(f"数据库已有 {campaign_count} 个 Campaign，跳过初始化")
            return

        # 确保 App 存在
        app = db.query(App).filter(App.id == 1).first()
        if not app:
            app = App(
                id=1,
                name="Block Blast",
                bundle_id="com.example.blockblast",
                platform="ios",
                status="active"
            )
            db.add(app)
            db.commit()
            print("创建 App 成功")

        # ============ 创建 Campaigns ============
        campaigns_data = [
            {
                "id": 1,
                "name": "Campaign_US_IOS",
                "roi": 1.25,
                "spend": 12500,
                "total_budget": 15000,
                "installs": 5200,
                "cpi": 2.4,
                "target_cpi": 2.5,
                "status": "running",
                "health": "excellent",
                "media": "Meta",
                "dsp": "Meta Ads",
                "campaign_type": "App Install",
                "objective": "Installs",
                "bid_strategy": "Target Cost",
                "optimization_goal": "App Install",
                "country": "US",
                "platform": "iOS",
                "impressions": 1250000,
                "clicks": 32500,
                "ctr": 2.6,
                "start_date": date(2026, 6, 1),
                "daily_budget": 2000,
            },
            {
                "id": 2,
                "name": "Campaign_JP_Android",
                "roi": 0.92,
                "spend": 8300,
                "total_budget": 10000,
                "installs": 3100,
                "cpi": 2.68,
                "target_cpi": 2.8,
                "status": "running",
                "health": "good",
                "media": "Google",
                "dsp": "Google Ads",
                "campaign_type": "UAC",
                "objective": "Installs",
                "bid_strategy": "Max Conversions",
                "optimization_goal": "In-App Action",
                "country": "JP",
                "platform": "Android",
                "impressions": 890000,
                "clicks": 21500,
                "ctr": 2.4,
                "start_date": date(2026, 6, 5),
                "daily_budget": 1500,
            },
            {
                "id": 3,
                "name": "Campaign_DE_UAC",
                "roi": 0.65,
                "spend": 5200,
                "total_budget": 8000,
                "installs": 1800,
                "cpi": 2.89,
                "target_cpi": 2.5,
                "status": "warning",
                "health": "warning",
                "media": "Google",
                "dsp": "Google Ads",
                "campaign_type": "UAC",
                "objective": "ROAS",
                "bid_strategy": "Target ROAS",
                "optimization_goal": "Purchase",
                "country": "DE",
                "platform": "All",
                "impressions": 520000,
                "clicks": 12800,
                "ctr": 2.5,
                "start_date": date(2026, 6, 10),
                "daily_budget": 1200,
            },
            {
                "id": 4,
                "name": "Campaign_TikTok_GB",
                "roi": 1.18,
                "spend": 6800,
                "total_budget": 8000,
                "installs": 2750,
                "cpi": 2.47,
                "target_cpi": 2.6,
                "status": "running",
                "health": "good",
                "media": "TikTok",
                "dsp": "TikTok Ads",
                "campaign_type": "Value Optimization",
                "objective": "ROAS",
                "bid_strategy": "Lowest Cost",
                "optimization_goal": "App Install",
                "country": "GB",
                "platform": "iOS",
                "impressions": 720000,
                "clicks": 19800,
                "ctr": 2.75,
                "start_date": date(2026, 6, 8),
                "daily_budget": 1000,
            },
            {
                "id": 5,
                "name": "Campaign_CA_Social",
                "roi": 0.42,
                "spend": 3500,
                "total_budget": 5000,
                "installs": 1450,
                "cpi": 2.41,
                "target_cpi": 2.5,
                "status": "paused",
                "health": "danger",
                "media": "Meta",
                "dsp": "Meta Ads",
                "campaign_type": "App Install",
                "objective": "Installs",
                "bid_strategy": "Target Cost",
                "optimization_goal": "App Install",
                "country": "CA",
                "platform": "All",
                "impressions": 380000,
                "clicks": 9500,
                "ctr": 2.5,
                "start_date": date(2026, 6, 12),
                "daily_budget": 800,
            },
            {
                "id": 6,
                "name": "Draft_Campaign_FR",
                "roi": None,
                "spend": 0,
                "total_budget": 5000,
                "installs": 0,
                "cpi": None,
                "target_cpi": 2.5,
                "status": "draft",
                "health": "pending",
                "media": "Meta",
                "dsp": "Meta Ads",
                "campaign_type": "App Install",
                "objective": "Installs",
                "bid_strategy": "Target Cost",
                "optimization_goal": "App Install",
                "country": "FR",
                "platform": "iOS",
                "impressions": 0,
                "clicks": 0,
                "ctr": None,
                "start_date": None,
                "daily_budget": 800,
            },
        ]

        for cam_data in campaigns_data:
            cam = Campaign(app_id=1, **cam_data)
            cam.budget = cam_data["total_budget"]
            db.add(cam)

        db.commit()
        print(f"创建 {len(campaigns_data)} 个 Campaign 成功")

        # ============ 创建 AdGroups ============
        adgroups_data = [
            # Campaign 1 AdGroups
            {"id": 1, "campaign_id": 1, "name": "US-iOS-Action", "status": "running", "spend": 4500, "impressions": 450000, "clicks": 12000, "installs": 1900, "cpi": 2.37, "ctr": 2.67, "roi": 1.32},
            {"id": 2, "campaign_id": 1, "name": "US-iOS-Fun", "status": "running", "spend": 3800, "impressions": 380000, "clicks": 9800, "installs": 1580, "cpi": 2.40, "ctr": 2.58, "roi": 1.28},
            {"id": 3, "campaign_id": 1, "name": "US-iOS-Tutorial", "status": "running", "spend": 4200, "impressions": 420000, "clicks": 10700, "installs": 1720, "cpi": 2.44, "ctr": 2.55, "roi": 1.18},

            # Campaign 2 AdGroups
            {"id": 4, "campaign_id": 2, "name": "JP-Android-Main", "status": "running", "spend": 5200, "impressions": 560000, "clicks": 13500, "installs": 1950, "cpi": 2.67, "ctr": 2.41, "roi": 0.95},
            {"id": 5, "campaign_id": 2, "name": "JP-Android-Broad", "status": "running", "spend": 3100, "impressions": 330000, "clicks": 8000, "installs": 1150, "cpi": 2.70, "ctr": 2.42, "roi": 0.88},

            # Campaign 3 AdGroups
            {"id": 6, "campaign_id": 3, "name": "DE-UAC-Value", "status": "warning", "spend": 5200, "impressions": 520000, "clicks": 12800, "installs": 1800, "cpi": 2.89, "ctr": 2.46, "roi": 0.65},

            # Campaign 4 AdGroups
            {"id": 7, "campaign_id": 4, "name": "GB-TikTok-Creative", "status": "running", "spend": 6800, "impressions": 720000, "clicks": 19800, "installs": 2750, "cpi": 2.47, "ctr": 2.75, "roi": 1.18},

            # Campaign 5 AdGroups (paused)
            {"id": 8, "campaign_id": 5, "name": "CA-Social-Broad", "status": "paused", "spend": 3500, "impressions": 380000, "clicks": 9500, "installs": 1450, "cpi": 2.41, "ctr": 2.50, "roi": 0.42},
        ]

        for ag_data in adgroups_data:
            ag = AdGroup(**ag_data)
            db.add(ag)

        db.commit()
        print(f"创建 {len(adgroups_data)} 个 AdGroup 成功")

        # ============ 创建 Creatives ============
        creatives_data = [
            {
                "id": 1,
                "name": "US_Video_Action_001",
                "type": "video",
                "format": "mp4",
                "file_size": 15 * 1024 * 1024,
                "duration": 15,
                "resolution": "1080x1920",
                "url": "https://example.com/creative1.mp4",
                "thumbnail_url": "https://picsum.photos/200/300?random=1",
                "designer": "张三",
                "tags": ["动作", "战斗", "爆炸", "US"],
                "status": "active",
                "spend": 12500,
                "impressions": 1250000,
                "clicks": 32500,
                "installs": 5200,
                "ctr": 2.6,
                "cpc": 0.38,
                "cpi": 2.4,
                "roi": 1.25,
                "conversion_rate": 16.0,
                "performance_score": 85,
                "trend": "up",
            },
            {
                "id": 2,
                "name": "JP_Character_Gacha",
                "type": "image",
                "format": "jpg",
                "file_size": 2 * 1024 * 1024,
                "resolution": "1080x1080",
                "url": "https://example.com/creative2.jpg",
                "thumbnail_url": "https://picsum.photos/200/300?random=2",
                "designer": "李四",
                "tags": ["角色", "抽卡", "JP", "立绘"],
                "status": "active",
                "spend": 8300,
                "impressions": 890000,
                "clicks": 21500,
                "installs": 3100,
                "ctr": 2.4,
                "cpc": 0.39,
                "cpi": 2.68,
                "roi": 0.92,
                "conversion_rate": 14.4,
                "performance_score": 72,
                "trend": "stable",
            },
            {
                "id": 3,
                "name": "DE_Playable_Tutorial",
                "type": "playable",
                "format": "html",
                "file_size": 8 * 1024 * 1024,
                "duration": 30,
                "resolution": "1080x1920",
                "url": "https://example.com/creative3.html",
                "thumbnail_url": "https://picsum.photos/200/300?random=3",
                "designer": "王五",
                "tags": ["试玩", "教程", "DE", "互动"],
                "status": "active",
                "spend": 5200,
                "impressions": 520000,
                "clicks": 12800,
                "installs": 1800,
                "ctr": 2.5,
                "cpc": 0.41,
                "cpi": 2.89,
                "roi": 0.65,
                "conversion_rate": 14.1,
                "performance_score": 58,
                "trend": "down",
            },
            {
                "id": 4,
                "name": "GB_TikTok_Trend",
                "type": "video",
                "format": "mp4",
                "file_size": 12 * 1024 * 1024,
                "duration": 12,
                "resolution": "1080x1920",
                "url": "https://example.com/creative4.mp4",
                "thumbnail_url": "https://picsum.photos/200/300?random=4",
                "designer": "赵六",
                "tags": ["TikTok", "热梗", "GB", "竖版"],
                "status": "active",
                "spend": 6800,
                "impressions": 720000,
                "clicks": 19800,
                "installs": 2750,
                "ctr": 2.75,
                "cpc": 0.34,
                "cpi": 2.47,
                "roi": 1.18,
                "conversion_rate": 13.9,
                "performance_score": 78,
                "trend": "up",
            },
            {
                "id": 5,
                "name": "CA_Carousel_Features",
                "type": "carousel",
                "format": "jpg",
                "file_size": 5 * 1024 * 1024,
                "resolution": "1080x1080",
                "url": "https://example.com/creative5.html",
                "thumbnail_url": "https://picsum.photos/200/300?random=5",
                "designer": "张三",
                "tags": ["轮播", "玩法", "CA", "多图"],
                "status": "active",
                "spend": 3500,
                "impressions": 380000,
                "clicks": 9500,
                "installs": 1450,
                "ctr": 2.5,
                "cpc": 0.37,
                "cpi": 2.41,
                "roi": 0.42,
                "conversion_rate": 15.3,
                "performance_score": 45,
                "trend": "down",
            },
            {
                "id": 6,
                "name": "FR_Draft_NewYear",
                "type": "video",
                "format": "mp4",
                "file_size": 18 * 1024 * 1024,
                "duration": 20,
                "resolution": "1080x1920",
                "url": "https://example.com/creative6.mp4",
                "thumbnail_url": "https://picsum.photos/200/300?random=6",
                "designer": "李四",
                "tags": ["新年", "FR", "节庆"],
                "status": "draft",
                "spend": 0,
                "impressions": 0,
                "clicks": 0,
                "installs": 0,
                "ctr": None,
                "cpc": None,
                "cpi": None,
                "roi": None,
                "conversion_rate": None,
                "performance_score": 50,
                "trend": "stable",
            },
        ]

        for cr_data in creatives_data:
            cr = Creative(app_id=1, **cr_data)
            db.add(cr)

        db.commit()
        print(f"创建 {len(creatives_data)} 个 Creative 成功")

        # ============ 创建 Ads (关联 AdGroup 和 Creative) ============
        ads_data = [
            # AdGroup 1 ads
            {"id": 1, "ad_group_id": 1, "creative_id": 1, "name": "US-Action-Video-01", "status": "running", "ad_type": "video", "spend": 4500, "impressions": 450000, "clicks": 12000, "installs": 1900, "ctr": 2.67, "cpc": 0.375, "cpi": 2.37, "roi": 1.32, "conversion_rate": 15.8},

            # AdGroup 2 ads
            {"id": 2, "ad_group_id": 2, "creative_id": 1, "name": "US-Fun-Video-01", "status": "running", "ad_type": "video", "spend": 3800, "impressions": 380000, "clicks": 9800, "installs": 1580, "ctr": 2.58, "cpc": 0.388, "cpi": 2.40, "roi": 1.28, "conversion_rate": 16.1},

            # AdGroup 3 ads
            {"id": 3, "ad_group_id": 3, "creative_id": 1, "name": "US-Tutorial-Video-01", "status": "running", "ad_type": "video", "spend": 4200, "impressions": 420000, "clicks": 10700, "installs": 1720, "ctr": 2.55, "cpc": 0.393, "cpi": 2.44, "roi": 1.18, "conversion_rate": 16.1},

            # AdGroup 4 ads
            {"id": 4, "ad_group_id": 4, "creative_id": 2, "name": "JP-Main-Image-01", "status": "running", "ad_type": "image", "spend": 5200, "impressions": 560000, "clicks": 13500, "installs": 1950, "ctr": 2.41, "cpc": 0.385, "cpi": 2.67, "roi": 0.95, "conversion_rate": 14.4},

            # AdGroup 5 ads
            {"id": 5, "ad_group_id": 5, "creative_id": 2, "name": "JP-Broad-Image-01", "status": "running", "ad_type": "image", "spend": 3100, "impressions": 330000, "clicks": 8000, "installs": 1150, "ctr": 2.42, "cpc": 0.388, "cpi": 2.70, "roi": 0.88, "conversion_rate": 14.4},

            # AdGroup 6 ads
            {"id": 6, "ad_group_id": 6, "creative_id": 3, "name": "DE-Playable-01", "status": "warning", "ad_type": "playable", "spend": 5200, "impressions": 520000, "clicks": 12800, "installs": 1800, "ctr": 2.46, "cpc": 0.406, "cpi": 2.89, "roi": 0.65, "conversion_rate": 14.1},

            # AdGroup 7 ads
            {"id": 7, "ad_group_id": 7, "creative_id": 4, "name": "GB-TikTok-Trend-01", "status": "running", "ad_type": "video", "spend": 6800, "impressions": 720000, "clicks": 19800, "installs": 2750, "ctr": 2.75, "cpc": 0.343, "cpi": 2.47, "roi": 1.18, "conversion_rate": 13.9},

            # AdGroup 8 ads
            {"id": 8, "ad_group_id": 8, "creative_id": 5, "name": "CA-Carousel-Features", "status": "paused", "ad_type": "carousel", "spend": 3500, "impressions": 380000, "clicks": 9500, "installs": 1450, "ctr": 2.50, "cpc": 0.368, "cpi": 2.41, "roi": 0.42, "conversion_rate": 15.3},
        ]

        for ad_data in ads_data:
            ad = Ad(**ad_data)
            db.add(ad)

        db.commit()
        print(f"创建 {len(ads_data)} 个 Ad 成功")

        # ============ 创建 Alerts ============
        alerts_data = [
            {
                "id": 1,
                "alert_type": "roi_drop",
                "severity": "high",
                "message": "Campaign_DE_UAC ROI 下降 35%",
                "campaign_id": "3",
                "campaign_name": "Campaign_DE_UAC",
                "metric": "ROI D7",
                "current_value": 0.65,
                "previous_value": 1.00,
                "threshold": 0.8,
                "trend": "down",
                "affected_campaigns": [
                    {"id": "3", "name": "Campaign_DE_UAC", "spend": 5200, "roi": 0.65}
                ],
                "suggested_actions": [
                    "降低出价 10% 以控制 CPI",
                    "检查素材 CTR 表现",
                    "考虑暂停 ROI < 0.5 的广告组"
                ],
                "detected_at": datetime(2026, 6, 27, 12, 30, 0),
                "description": "ROI 连续 3 天呈下降趋势，已低于预警阈值",
                "status": "open"
            },
            {
                "id": 2,
                "alert_type": "cpi_rise",
                "severity": "high",
                "message": "Campaign_CA_Social CPI 上升 45%",
                "campaign_id": "5",
                "campaign_name": "Campaign_CA_Social",
                "metric": "CPI",
                "current_value": 2.41,
                "previous_value": 1.66,
                "threshold": 2.2,
                "trend": "up",
                "affected_campaigns": [
                    {"id": "5", "name": "Campaign_CA_Social", "spend": 3500, "cpi": 2.41}
                ],
                "suggested_actions": [
                    "检查转化质量变化",
                    "优化定向策略",
                    "考虑提高出价上限"
                ],
                "detected_at": datetime(2026, 6, 27, 13, 15, 0),
                "description": "CPI 突然上升，可能因竞价环境变化或素材衰减导致",
                "status": "open"
            },
            {
                "id": 3,
                "alert_type": "spend_drop",
                "severity": "medium",
                "message": "Campaign_JP_Android 花费下降 20%",
                "campaign_id": "2",
                "campaign_name": "Campaign_JP_Android",
                "metric": "Spend",
                "current_value": 8300,
                "previous_value": 10375,
                "threshold": -15,
                "trend": "down",
                "affected_campaigns": [
                    {"id": "2", "name": "Campaign_JP_Android", "spend": 8300, "roi": 0.92}
                ],
                "suggested_actions": [
                    "检查账户余额是否充足",
                    "检查 Campaign 是否正常投放",
                    "检查媒体端是否有政策违规通知"
                ],
                "detected_at": datetime(2026, 6, 27, 14, 0, 0),
                "description": "今日花费较昨日下降超过 15%，可能存在投放异常",
                "status": "open"
            }
        ]

        for alert_data in alerts_data:
            alert = Alert(app_id=1, **alert_data)
            db.add(alert)

        db.commit()
        print(f"创建 {len(alerts_data)} 个 Alert 成功")

        print("\n" + "=" * 50)
        print("数据初始化完成！")
        print(f"Campaign: {db.query(Campaign).count()}")
        print(f"AdGroup: {db.query(AdGroup).count()}")
        print(f"Ad: {db.query(Ad).count()}")
        print(f"Creative: {db.query(Creative).count()}")
        print(f"Alert: {db.query(Alert).count()}")
        print("=" * 50)

    except Exception as e:
        print(f"初始化失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_demo_data()
