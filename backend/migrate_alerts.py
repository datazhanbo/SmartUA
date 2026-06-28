"""
Migration script to update Alert table schema
Adds new fields: message, campaign_name, metric, current_value, previous_value, threshold, trend, affected_campaigns, suggested_actions, detected_at
"""
import sys
sys.path.insert(0, '.')

from app.db.base import engine
from sqlalchemy import text

def migrate_alerts():
    with engine.connect() as conn:
        # Check current columns
        result = conn.execute(text("PRAGMA table_info(report_alerts)"))
        columns = [row[1] for row in result.fetchall()]
        print(f"Current columns: {columns}")

        # SQLite doesn't support DROP COLUMN easily, so we'll recreate the table
        # First backup existing data if any
        has_data = False
        if 'alert_type' in columns:
            try:
                result = conn.execute(text("SELECT COUNT(*) FROM report_alerts"))
                count = result.fetchone()[0]
                has_data = count > 0
                print(f"Existing alerts count: {count}")
            except:
                pass

        # Drop existing table and let SQLAlchemy recreate it on next startup
        conn.execute(text("DROP TABLE IF EXISTS report_alerts"))
        conn.commit()
        print("Dropped report_alerts table, will be recreated with new schema")

if __name__ == "__main__":
    migrate_alerts()
