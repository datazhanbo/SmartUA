from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Numeric, Date, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Campaign(Base):
    """广告活动表"""
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 基本信息
    name = Column(String(256), nullable=False, index=True)
    external_id = Column(String(128), index=True)  # 媒体平台ID

    # 状态流: draft → approved → api_submitted → running → paused → ended
    status = Column(String(32), default="draft", index=True)

    # 媒体 & DSP 配置
    media = Column(String(64), index=True)  # Meta, Google, TikTok 等
    dsp = Column(String(64))
    account_id = Column(String(128))

    # 投放类型 & 目标
    campaign_type = Column(String(64))  # App Install, UAC, Traffic
    objective = Column(String(64))  # Installs, ROAS, Purchases
    bid_strategy = Column(String(64))  # Target Cost, Max Conversions
    optimization_goal = Column(String(64))  # App Install, Purchase

    # 定向设置
    country = Column(String(8), index=True)
    platform = Column(String(16))  # iOS, Android, All

    # 预算
    daily_budget = Column(Numeric(18, 4))
    total_budget = Column(Numeric(18, 4))
    spend = Column(Numeric(18, 4), default=0)
    target_cpi = Column(Numeric(18, 4))

    # 时间
    start_date = Column(Date)
    end_date = Column(Date)
    last_synced_at = Column(DateTime)

    # 健康度 & 性能指标（聚合计算）
    health = Column(String(16), default="pending")
    roi = Column(Numeric(10, 6))
    cpi = Column(Numeric(18, 4))
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    installs = Column(Integer, default=0)
    ctr = Column(Numeric(10, 6))

    # 扩展字段
    tags = Column(JSON)
    config_json = Column(JSON)
    notes = Column(String(1024))

    # 关联
    ad_groups = relationship("AdGroup", back_populates="campaign", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_campaign_status", "app_id", "status"),
        Index("idx_campaign_media", "app_id", "media"),
    )


class AdGroup(Base):
    """广告组表"""
    __tablename__ = "ad_groups"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    name = Column(String(256), nullable=False)
    external_id = Column(String(128), index=True)

    # 状态流
    status = Column(String(32), default="draft", index=True)

    # 出价 & 预算
    bid_amount = Column(Numeric(18, 4))
    daily_budget = Column(Numeric(18, 4))

    # 定向
    audience_json = Column(JSON)
    geo_targets = Column(JSON)
    device_types = Column(JSON)

    # 性能指标
    spend = Column(Numeric(18, 4), default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    installs = Column(Integer, default=0)
    cpi = Column(Numeric(18, 4))
    ctr = Column(Numeric(10, 6))
    roi = Column(Numeric(10, 6))

    # 关联
    campaign = relationship("Campaign", back_populates="ad_groups")
    ads = relationship("Ad", back_populates="ad_group", cascade="all, delete-orphan")


class Ad(Base):
    """广告表"""
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    ad_group_id = Column(Integer, ForeignKey("ad_groups.id"), nullable=False, index=True)
    creative_id = Column(Integer, ForeignKey("creatives.id"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    name = Column(String(256), nullable=False)
    external_id = Column(String(128), index=True)

    # 状态流
    status = Column(String(32), default="draft", index=True)

    # 广告类型
    ad_type = Column(String(32))  # video, image, carousel
    placement = Column(String(64))  # feed, story, search

    # 文案
    title = Column(String(512))
    body = Column(String(2048))
    cta_text = Column(String(64))

    # 性能指标
    spend = Column(Numeric(18, 4), default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    installs = Column(Integer, default=0)
    ctr = Column(Numeric(10, 6))
    cpc = Column(Numeric(18, 4))
    cpi = Column(Numeric(18, 4))
    roi = Column(Numeric(10, 6))
    conversion_rate = Column(Numeric(10, 6))

    # 关联
    ad_group = relationship("AdGroup", back_populates="ads")
    creative = relationship("Creative", back_populates="ads")


class Creative(Base):
    """素材表"""
    __tablename__ = "creatives"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    name = Column(String(256), nullable=False)

    # 素材类型
    type = Column(String(32), index=True)  # video, image, playable, carousel
    format = Column(String(32))  # mp4, jpg, png, html

    # 文件信息
    file_size = Column(Integer)  # bytes
    duration = Column(Integer)  # seconds (for video)
    resolution = Column(String(32))  # 1080x1920

    # 资源地址
    url = Column(String(1024))
    thumbnail_url = Column(String(1024))

    # 设计师 & 标签
    designer = Column(String(128))
    tags = Column(JSON)

    # 状态
    status = Column(String(32), default="active", index=True)

    # 性能指标 (聚合)
    spend = Column(Numeric(18, 4), default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    installs = Column(Integer, default=0)
    ctr = Column(Numeric(10, 6))
    cpc = Column(Numeric(18, 4))
    cpi = Column(Numeric(18, 4))
    roi = Column(Numeric(10, 6))
    conversion_rate = Column(Numeric(10, 6))

    # 表现评分
    performance_score = Column(Integer, default=50)
    trend = Column(String(16), default="stable")

    # 最后使用时间
    last_used_at = Column(DateTime)

    # 关联
    ads = relationship("Ad", back_populates="creative")

    __table_args__ = (
        Index("idx_creative_type", "app_id", "type"),
        Index("idx_creative_status", "app_id", "status"),
    )


class AdCreative(Base):
    """广告-素材多对多关联表（用于轮播等多素材广告）"""
    __tablename__ = "ad_creative_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ad_id = Column(Integer, ForeignKey("ads.id"), nullable=False, index=True)
    creative_id = Column(Integer, ForeignKey("creatives.id"), nullable=False, index=True)
    position = Column(Integer, default=0)  # 排序位置
    created_at = Column(DateTime, default=datetime.utcnow)
