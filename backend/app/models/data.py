from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, BigInteger, Text, Numeric, Date, Index
from datetime import datetime
from app.db.base import Base


class ConnectorCredential(Base):
    """连接器凭证配置"""
    __tablename__ = "connector_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = Column(String(32), nullable=False, index=True)
    account_name = Column(String(128), nullable=False)
    account_id = Column(String(64), index=True)

    status = Column(String(16), default="active", index=True)
    is_verified = Column(Boolean, default=False)
    last_verified_at = Column(DateTime)

    auth_type = Column(String(32), default="api_key")
    credentials_json = Column(JSON, nullable=False)

    sync_frequency = Column(String(32), default="daily")
    auto_sync_enabled = Column(Boolean, default=False)

    params = Column(JSON)
    notes = Column(Text)

    __table_args__ = (
        Index("idx_credential_platform", "app_id", "platform", "account_id", unique=True),
    )


class ConnectorRun(Base):
    """连接运行记录"""
    __tablename__ = "connector_runs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    connector = Column(String(32), nullable=False)
    source_type = Column(String(32), nullable=False)
    operation = Column(String(32), nullable=False)
    report_type = Column(String(32), nullable=False)
    date_from = Column(Date)
    date_to = Column(Date)
    account_id = Column(String(64))
    app_key = Column(String(64))
    currency = Column(String(8), default="USD")
    params_json = Column(JSON)
    status = Column(String(16), default="running")
    raw_row_count = Column(Integer, default=0)
    normalized_row_count = Column(Integer, default=0)
    error_detail = Column(Text)
    adapter_response_json = Column(JSON)
    executed_by = Column(Integer, ForeignKey("users.id"))


class RawPayload(Base):
    """原始API数据"""
    __tablename__ = "raw_payloads"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(BigInteger, ForeignKey("connector_runs.id"))
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    connector = Column(String(32), nullable=False)
    source_type = Column(String(32), nullable=False)
    report_type = Column(String(32), nullable=False)
    endpoint = Column(Text)
    account_id = Column(String(64))
    app_key = Column(String(64))
    date_from = Column(Date)
    date_to = Column(Date)
    request_hash = Column(String(64))
    payload_hash = Column(String(64))
    row_count = Column(Integer)
    payload_json = Column(JSON, nullable=False)
    file_size_bytes = Column(Integer)


class FactMediaDaily(Base):
    """媒体事实表（DWD）"""
    __tablename__ = "fact_media_daily"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(BigInteger, ForeignKey("connector_runs.id"))
    raw_payload_id = Column(BigInteger, ForeignKey("raw_payloads.id"))
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    source_platform = Column(String(32), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    date = Column(Date, nullable=False, index=True)
    account_id = Column(String(64), index=True)
    app_key = Column(String(64), index=True)
    media_source = Column(String(64), index=True)
    campaign_id = Column(String(128), index=True)
    campaign_name = Column(String(512))
    adset_id = Column(String(128), index=True)
    adset_name = Column(String(512))
    ad_id = Column(String(128), index=True)
    ad_name = Column(String(512))
    creative_id = Column(String(128), index=True)
    creative_name = Column(String(512))
    country = Column(String(8), index=True)
    currency = Column(String(8), default="USD")

    impressions = Column(BigInteger)
    clicks = Column(BigInteger)
    spend = Column(Numeric(18, 4))
    spend_usd = Column(Numeric(18, 4))
    media_installs = Column(BigInteger)
    media_conversions = Column(BigInteger)
    ctr = Column(Numeric(10, 6))
    cpc = Column(Numeric(18, 4))
    cpm = Column(Numeric(18, 4))
    cpi = Column(Numeric(18, 4))

    source_row_hash = Column(String(64), unique=True, nullable=False)
    raw_row_json = Column(JSON)

    __table_args__ = (
        Index("idx_media_agg", "app_id", "app_key", "date", "campaign_id"),
    )


class FactMMPDaily(Base):
    """MMP事实表（DWD）"""
    __tablename__ = "fact_mmp_daily"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(BigInteger, ForeignKey("connector_runs.id"))
    raw_payload_id = Column(BigInteger, ForeignKey("raw_payloads.id"))
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    mmp = Column(String(32), nullable=False, default="appsflyer")
    date = Column(Date, nullable=False, index=True)
    app_key = Column(String(64), nullable=False, index=True)
    platform = Column(String(16))
    media_source = Column(String(64), index=True)
    campaign_id = Column(String(128), index=True)
    campaign_name = Column(String(512))
    adset_id = Column(String(128))
    adset_name = Column(String(512))
    ad_id = Column(String(128))
    ad_name = Column(String(512))
    country = Column(String(8), index=True)
    attribution_model = Column(String(32), default="aggregate")
    signal_confidence = Column(String(16), default="medium")
    currency = Column(String(8), default="USD")

    attributed_installs = Column(BigInteger)
    registrations = Column(BigInteger)
    payers = Column(BigInteger)
    cost = Column(Numeric(18, 4))
    cost_usd = Column(Numeric(18, 4))
    revenue = Column(Numeric(18, 4))
    revenue_usd = Column(Numeric(18, 4))

    roi_d0 = Column(Numeric(10, 6))
    roi_d1 = Column(Numeric(10, 6))
    roi_d3 = Column(Numeric(10, 6))
    roi_d7 = Column(Numeric(10, 6))
    roi_d14 = Column(Numeric(10, 6))
    roi_d30 = Column(Numeric(10, 6))
    roi_d60 = Column(Numeric(10, 6))
    roi_d90 = Column(Numeric(10, 6))

    retention_d1 = Column(Numeric(10, 6))
    retention_d3 = Column(Numeric(10, 6))
    retention_d7 = Column(Numeric(10, 6))
    retention_d14 = Column(Numeric(10, 6))
    retention_d30 = Column(Numeric(10, 6))

    source_row_hash = Column(String(64), unique=True, nullable=False)
    raw_row_json = Column(JSON)

    __table_args__ = (
        Index("idx_mmp_agg", "app_id", "app_key", "date", "campaign_id"),
    )


class AggUADaily(Base):
    """UA聚合日报表（DWS）"""
    __tablename__ = "agg_ua_daily"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    active_date = Column(Date, nullable=False, index=True)
    app_key = Column(String(64), index=True)
    bundle_name = Column(String(128))
    media_source = Column(String(64), index=True)
    source_platform = Column(String(32), index=True)
    country = Column(String(8), index=True)
    account_id = Column(String(64))
    campaign_id = Column(String(128), index=True)
    campaign_name = Column(String(512))
    adset_id = Column(String(128))
    adset_name = Column(String(512))
    ad_id = Column(String(128))
    ad_name = Column(String(512))
    creative_id = Column(String(128))

    match_status = Column(String(16), default="unknown")
    signal_confidence = Column(String(16))

    total_shows = Column(BigInteger)
    total_clicks = Column(BigInteger)
    total_cost = Column(Numeric(18, 4))
    total_cost_usd = Column(Numeric(18, 4))

    total_registers = Column(BigInteger)
    total_media_installs = Column(BigInteger)
    total_mmp_installs = Column(BigInteger)
    total_revenue = Column(Numeric(18, 4))
    total_revenue_usd = Column(Numeric(18, 4))

    ctr = Column(Numeric(10, 6))
    cpm = Column(Numeric(18, 4))
    cpc = Column(Numeric(18, 4))
    af_cpi = Column(Numeric(18, 4))
    af_cvr = Column(Numeric(10, 6))
    af_arpu = Column(Numeric(18, 4))
    ipm = Column(Numeric(10, 6))

    roi_0 = Column(Numeric(10, 6))
    roi_1 = Column(Numeric(10, 6))
    roi_3 = Column(Numeric(10, 6))
    roi_7 = Column(Numeric(10, 6))
    roi_14 = Column(Numeric(10, 6))
    roi_30 = Column(Numeric(10, 6))
    roi_60 = Column(Numeric(10, 6))

    retention_1 = Column(Numeric(10, 6))
    retention_3 = Column(Numeric(10, 6))
    retention_7 = Column(Numeric(10, 6))
    retention_14 = Column(Numeric(10, 6))
    retention_30 = Column(Numeric(10, 6))

    is_forecast = Column(Boolean, default=False)
    forecast_version = Column(String(16))

    __table_args__ = (
        Index("idx_ua_agg", "app_id", "active_date", "campaign_id", "source_platform"),
    )


class CampaignHealth(Base):
    """Campaign健康度快照"""
    __tablename__ = "report_campaign_health"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    campaign_id = Column(String(128), nullable=False, index=True)
    campaign_name = Column(String(512))
    media_source = Column(String(64))

    health_score = Column(Integer)
    health_level = Column(String(16), index=True)
    lifecycle_phase = Column(String(16))

    roi_score = Column(Integer)
    retention_score = Column(Integer)
    spend_stability_score = Column(Integer)
    scale_potential_score = Column(Integer)

    roi_d7 = Column(Numeric(10, 6))
    retention_d7 = Column(Numeric(10, 6))
    spend_trend = Column(String(16))
    daily_spend = Column(Numeric(18, 4))
    cpi_d7 = Column(Numeric(18, 4))

    suggestion = Column(Text)
    alert_level = Column(String(16), default="none")
    suggested_action = Column(JSON)


class Alert(Base):
    """异常预警记录"""
    __tablename__ = "report_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    alert_type = Column(String(32), nullable=False, index=True)
    severity = Column(String(16), nullable=False, index=True)
    status = Column(String(16), default="open", index=True)

    campaign_id = Column(String(128), index=True)
    campaign_name = Column(String(512))
    creative_id = Column(String(128))
    country = Column(String(8))
    media_source = Column(String(64))

    metric = Column(String(64))
    current_value = Column(Numeric(18, 4))
    previous_value = Column(Numeric(18, 4))
    threshold = Column(Numeric(18, 4))
    change_percent = Column(Numeric(10, 4))
    trend = Column(String(16))

    message = Column(String(512))
    description = Column(Text)
    affected_campaigns = Column(JSON)
    suggested_actions = Column(JSON)
    detected_at = Column(DateTime)

    resolved_by = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    resolution_note = Column(Text)

    notified_channels = Column(JSON)
    notification_sent_at = Column(DateTime)


class DashboardCache(Base):
    """Dashboard缓存"""
    __tablename__ = "dashboard_cache"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    cache_key = Column(String(128), nullable=False, unique=True)
    data_json = Column(JSON, nullable=False)
    refreshed_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


class DimCampaignStructure(Base):
    """计划分层/运营态维度表（DIM，current snapshot）。

    解决原 current_summary() 把 status / daily_budget / creative_age 硬编码为
    ACTIVE / None 的问题：媒体连接器 pull_structure() 拉取 Campaign-&gt;AdSet-&gt;Ad-&gt;Creative
    层级与运营态（status / 预算 / 出价 / 定向），upsert 进本表。current_summary() 改读
    本表得到真实运营态。

    设计取舍：单 current row（按 app_id+platform+entity_level+entity_id upsert），
    version/as_of_date 记录最近一次刷新；完整历史可从 raw_payloads 回溯。SCD Type-2
    历史（effective_from/to）为后续增强项，当前不实现以避免写放大与触发复杂度。
    """

    __tablename__ = "dim_campaign_structure"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_platform = Column(String(32), nullable=False, index=True)  # meta/google/tiktok
    account_id = Column(String(64), index=True)

    entity_level = Column(String(16), nullable=False, index=True)  # campaign/adset/ad/creative
    entity_id = Column(String(128), nullable=False, index=True)     # 该层级自身 ID
    parent_id = Column(String(128), index=True)                     # campaign_id（逐层上溯）

    campaign_id = Column(String(128), index=True)
    campaign_name = Column(String(512))
    adset_id = Column(String(128), index=True)
    adset_name = Column(String(512))
    ad_id = Column(String(128), index=True)
    ad_name = Column(String(512))
    creative_id = Column(String(128), index=True)
    creative_name = Column(String(512))

    status = Column(String(32))
    daily_budget = Column(Numeric(18, 4))
    bid_amount = Column(Numeric(18, 4))
    currency = Column(String(8), default="USD")
    targeting_json = Column(JSON)

    as_of_date = Column(Date, index=True)       # 最近一次刷新日
    first_seen_date = Column(Date)              # 首次出现日（用于 creative/age 计算）
    version = Column(Integer, default=1)

    __table_args__ = (
        Index("idx_struct_upsert", "app_id", "source_platform", "entity_level", "entity_id", unique=True),
    )


class DimFxRate(Base):
    """币种汇率维度表（DIM）：1 quote_currency = rate USD。

    spend_usd 由连接器 normalize() 经 to_usd() 计算：优先查本表最新汇率，
    缺失则回退静态 FX 表（base.py _FX_STATIC），再缺失则视为 1.0 并告警。
    """

    __tablename__ = "dim_fx_rate"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    base_currency = Column(String(8), default="USD", nullable=False)
    quote_currency = Column(String(8), nullable=False, index=True)
    rate = Column(Numeric(18, 8), nullable=False)
    as_of_date = Column(Date, index=True)
    source = Column(String(32), default="static")
