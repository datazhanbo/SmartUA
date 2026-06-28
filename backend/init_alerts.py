"""
Initialize Alert data
"""
import sys
from datetime import datetime

sys.path.insert(0, '.')

from app.db.base import SessionLocal
from app.models.data import Alert
from app.models.sys import User  # Import User to register table in metadata


def init_alerts():
    db = SessionLocal()

    try:
        # Check if alerts already exist
        alert_count = db.query(Alert).count()
        if alert_count > 0:
            print(f"数据库已有 {alert_count} 个 Alert，跳过初始化")
            return

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

    except Exception as e:
        print(f"初始化失败: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    init_alerts()
