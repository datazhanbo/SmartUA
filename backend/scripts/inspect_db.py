#!/usr/bin/env python3
"""
数据库结构检查脚本
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base, engine, SessionLocal
from sqlalchemy import inspect, func

def inspect_database():
    """检查数据库结构"""
    inspector = inspect(engine)

    print("=" * 80)
    print("📊 SmartUA 数据库结构概览")
    print("=" * 80)

    # 获取所有表名
    table_names = inspector.get_table_names()
    print(f"\n总表数: {len(table_names)}")

    tables_info = {}

    for table_name in table_names:
        print(f"\n{'='*60}")
        print(f"📋 表: {table_name}")
        print(f"{'='*60}")

        # 获取列信息
        columns = inspector.get_columns(table_name)
        print(f"\n列数: {len(columns)}")
        print("\n列信息:")
        for col in columns:
            pk_mark = " 🔑(PK)" if col.get('primary_key') else ""
            nullable_mark = "" if col.get('nullable') else " *"
            print(f"  - {col['name']:<30} {str(col['type']):<20}{pk_mark}{nullable_mark}")

        # 获取主键
        pk = inspector.get_primary_key_constraint(table_name)
        if pk:
            print(f"\n主键: {pk['constrained_columns']}")

        # 获取外键
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print(f"\n外键数: {len(fks)}")
            for fk in fks:
                print(f"  - {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")

        # 获取索引
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print(f"\n索引数: {len(indexes)}")
            for idx in indexes:
                unique_mark = " [UNIQUE]" if idx.get('unique') else ""
                print(f"  - {idx['name']}: {idx['column_names']}{unique_mark}")

        # 获取行数
        db = SessionLocal()
        try:
            table = Base.metadata.tables[table_name]
            count = db.query(func.count()).select_from(table).scalar()
            print(f"\n行数: {count}")
        except Exception as e:
            print(f"\n行数: 无法获取 ({e})")
        finally:
            db.close()

        tables_info[table_name] = {
            'columns': columns,
            'row_count': count if 'count' in locals() else 0,
            'foreign_keys': fks,
            'indexes': indexes
        }

    print("\n" + "=" * 80)
    print("📊 数据库统计")
    print("=" * 80)
    total_rows = sum(info['row_count'] for info in tables_info.values())
    print(f"\n总数据行数: {total_rows}")
    print(f"总表数: {len(tables_info)}")

    # 按模块分组
    print("\n按模块分组:")
    modules = {
        '系统表': [t for t in table_names if t in ['users', 'roles', 'permissions', 'user_roles', 'apps', 'user_app_bindings', 'audit_logs', 'menus']],
        '数仓ODS层': [t for t in table_names if t in ['connector_runs', 'raw_payloads']],
        '数仓DWD层': [t for t in table_names if t in ['fact_media_daily', 'fact_mmp_daily']],
        '数仓DWS层': [t for t in table_names if t in ['agg_ua_daily']],
        '数仓ADS层': [t for t in table_names if t in ['report_campaign_health', 'report_alerts', 'dashboard_cache']],
        '意图引擎': [t for t in table_names if t in ['intent_executions', 'action_logs', 'strategy_templates']],
    }

    for module, tables in modules.items():
        if tables:
            print(f"\n  {module}:")
            for t in tables:
                count = tables_info.get(t, {}).get('row_count', 0)
                print(f"    - {t} ({count} 行)")

    return tables_info

if __name__ == '__main__':
    inspect_database()
