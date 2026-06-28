"""
数据管理 API - 查看底层数据、表结构、数据预览
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, func, text, Table, MetaData
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from app.db.base import get_db, Base, engine
from app.core.security import get_current_user
from app.models.sys import User

router = APIRouter(prefix="/data-management", tags=["data-management"])

# 数据字典 - 表说明
TABLE_DESCRIPTIONS = {
    # 系统表
    'users': '用户表 - 存储系统用户基本信息',
    'roles': '角色表 - 系统角色定义（管理员/优化师/分析师/财务）',
    'permissions': '权限表 - 功能权限定义',
    'user_roles': '用户角色关联表 - 用户与角色多对多关系',
    'apps': '应用表 - 多租户隔离的应用（游戏/产品）',
    'user_app_bindings': '用户应用绑定表 - 用户可访问的应用范围',
    'audit_logs': '审计日志 - 记录用户操作日志',
    'menus': '菜单表 - 前端菜单配置',

    # ODS层 - 原始数据
    'connector_runs': '连接器运行记录 - 各平台数据同步任务记录',
    'raw_payloads': '原始API响应 - 媒体平台API返回的原始数据备份',

    # DWD层 - 明细数据
    'fact_media_daily': '媒体日事实表 - Meta/Google/TikTok等媒体投放明细',
    'fact_mmp_daily': 'MMP日事实表 - AppsFlyer等归因平台转化数据',

    # DWS层 - 聚合数据
    'agg_ua_daily': '用户获取聚合表 - ROI360核心宽表，多维度聚合',

    # ADS层 - 应用服务
    'report_campaign_health': 'Campaign健康度报表 - 自动评分与建议',
    'report_alerts': '异常告警表 - 智能检测的异常事件',
    'dashboard_cache': 'Dashboard缓存 - 提升前端加载速度',

    # 意图引擎
    'intent_executions': '意图执行记录 - 自然语言操作的完整生命周期',
    'action_logs': '操作日志 - 实际执行的投放操作记录',
    'strategy_templates': '策略模板 - 可复用的优化策略配置',
}

# 表分组
TABLE_GROUPS = {
    '系统管理': ['users', 'roles', 'permissions', 'user_roles', 'apps', 'user_app_bindings', 'audit_logs', 'menus'],
    'ODS层(原始数据)': ['connector_runs', 'raw_payloads'],
    'DWD层(明细数据)': ['fact_media_daily', 'fact_mmp_daily'],
    'DWS层(聚合数据)': ['agg_ua_daily'],
    'ADS层(应用服务)': ['report_campaign_health', 'report_alerts', 'dashboard_cache'],
    '意图引擎': ['intent_executions', 'action_logs', 'strategy_templates'],
}


@router.get("/tables")
async def get_table_list(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取所有数据表列表及基本信息"""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    tables_info = []
    for table_name in table_names:
        # 获取列数
        columns = inspector.get_columns(table_name)
        # 获取行数
        try:
            row_count = db.execute(text(f"SELECT COUNT(*) FROM '{table_name}'")).scalar()
        except:
            row_count = 0

        # 获取索引数
        try:
            indexes = inspector.get_indexes(table_name)
            index_count = len(indexes)
        except:
            index_count = 0

        tables_info.append({
            'name': table_name,
            'description': TABLE_DESCRIPTIONS.get(table_name, ''),
            'column_count': len(columns),
            'row_count': row_count,
            'index_count': index_count,
        })

    # 按组分组
    grouped_tables = {}
    for group_name, group_tables in TABLE_GROUPS.items():
        grouped_tables[group_name] = [t for t in tables_info if t['name'] in group_tables]

    # 其他表
    all_grouped = set()
    for g_tables in grouped_tables.values():
        all_grouped.update(t['name'] for t in g_tables)
    other_tables = [t for t in tables_info if t['name'] not in all_grouped]
    if other_tables:
        grouped_tables['其他'] = other_tables

    return {
        'total_tables': len(tables_info),
        'total_rows': sum(t['row_count'] for t in tables_info),
        'grouped_tables': grouped_tables,
        'flat_list': tables_info
    }


@router.get("/tables/{table_name}/schema")
async def get_table_schema(
    table_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取指定表的详细结构信息"""
    inspector = inspect(engine)

    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    columns = inspector.get_columns(table_name)
    primary_keys = inspector.get_pk_constraint(table_name)
    foreign_keys = inspector.get_foreign_keys(table_name)
    indexes = inspector.get_indexes(table_name)

    return {
        'name': table_name,
        'description': TABLE_DESCRIPTIONS.get(table_name, ''),
        'columns': [
            {
                'name': col['name'],
                'type': str(col['type']),
                'nullable': col.get('nullable', True),
                'is_primary_key': col['name'] in primary_keys.get('constrained_columns', []),
                'default': str(col.get('default', '')) if col.get('default') else None
            }
            for col in columns
        ],
        'primary_key': primary_keys.get('constrained_columns', []),
        'foreign_keys': [
            {
                'columns': fk['constrained_columns'],
                'ref_table': fk['referred_table'],
                'ref_columns': fk['referred_columns']
            }
            for fk in foreign_keys
        ],
        'indexes': [
            {
                'name': idx['name'],
                'columns': idx['column_names'],
                'unique': idx.get('unique', False)
            }
            for idx in indexes
        ]
    }


@router.get("/tables/{table_name}/preview")
async def get_table_preview(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取表数据预览"""
    inspector = inspect(engine)

    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    # 获取总行数
    total = db.execute(text(f"SELECT COUNT(*) FROM '{table_name}'")).scalar()

    # 分页查询
    offset = (page - 1) * page_size
    result = db.execute(text(f"SELECT * FROM '{table_name}' LIMIT :limit OFFSET :offset"),
                        {"limit": page_size, "offset": offset})

    columns = result.keys()
    rows = [dict(zip(columns, row)) for row in result.fetchall()]

    return {
        'table_name': table_name,
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size,
        'columns': list(columns),
        'rows': rows
    }


@router.get("/tables/{table_name}/stats")
async def get_table_stats(
    table_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取表的统计信息"""
    inspector = inspect(engine)

    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    columns = inspector.get_columns(table_name)
    numeric_columns = [
        col['name'] for col in columns
        if 'INTEGER' in str(col['type']).upper() or 'NUMERIC' in str(col['type']).upper()
    ]

    stats = {}

    # 如果是数值列，计算基础统计
    if numeric_columns:
        for col in numeric_columns[:5]:  # 最多统计5列
            try:
                result = db.execute(text(f"""
                    SELECT
                        MIN({col}),
                        MAX({col}),
                        AVG({col}),
                        SUM({col})
                    FROM '{table_name}'
                """)).fetchone()
                stats[col] = {
                    'min': float(result[0]) if result[0] else None,
                    'max': float(result[1]) if result[1] else None,
                    'avg': float(result[2]) if result[2] else None,
                    'sum': float(result[3]) if result[3] else None
                }
            except:
                continue

    # 时间列范围
    date_columns = [col['name'] for col in columns if 'DATE' in str(col['type']).upper() or 'TIME' in str(col['type']).upper()]
    date_ranges = {}
    for col in date_columns[:3]:
        try:
            result = db.execute(text(f"SELECT MIN({col}), MAX({col}) FROM '{table_name}'")).fetchone()
            date_ranges[col] = {
                'min': str(result[0]) if result[0] else None,
                'max': str(result[1]) if result[1] else None
            }
        except:
            continue

    return {
        'table_name': table_name,
        'stats': stats,
        'date_ranges': date_ranges,
        'column_count': len(columns)
    }


@router.get("/relations")
async def get_database_relations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取数据库表关系图数据"""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    relations = []
    for table_name in table_names:
        fks = inspector.get_foreign_keys(table_name)
        for fk in fks:
            relations.append({
                'source_table': table_name,
                'source_columns': fk['constrained_columns'],
                'target_table': fk['referred_table'],
                'target_columns': fk['referred_columns'],
                'relation_type': 'many_to_one'
            })

    return {
        'tables': [
            {
                'name': t,
                'description': TABLE_DESCRIPTIONS.get(t, ''),
                'group': next((g for g, ts in TABLE_GROUPS.items() if t in ts), '其他')
            }
            for t in table_names
        ],
        'relations': relations,
        'groups': list(TABLE_GROUPS.keys())
    }


@router.get("/summary")
async def get_data_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取数据总览"""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    # 各层数据量
    layer_stats = {}
    for layer, tables in TABLE_GROUPS.items():
        layer_rows = 0
        for t in tables:
            if t in table_names:
                try:
                    count = db.execute(text(f"SELECT COUNT(*) FROM '{t}'")).scalar()
                    layer_rows += count
                except:
                    pass
        layer_stats[layer] = layer_rows

    # 时间范围
    try:
        agg_date_range = db.execute(text("SELECT MIN(active_date), MAX(active_date) FROM agg_ua_daily")).fetchone()
    except:
        agg_date_range = (None, None)

    return {
        'layer_stats': layer_stats,
        'data_date_range': {
            'start': str(agg_date_range[0]) if agg_date_range[0] else None,
            'end': str(agg_date_range[1]) if agg_date_range[1] else None
        },
        'total_tables': len(table_names),
        'total_rows': sum(layer_stats.values()),
        'apps_count': db.execute(text("SELECT COUNT(*) FROM apps")).scalar(),
        'users_count': db.execute(text("SELECT COUNT(*) FROM users")).scalar(),
    }
