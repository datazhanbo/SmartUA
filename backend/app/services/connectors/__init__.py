import logging
from typing import Any, Dict, Type, Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from .base import BaseConnector
from .meta import MetaConnector
from .google import GoogleAdsConnector
from .appsflyer import AppsFlyerConnector
from .mock_media import MockMediaConnector
from .tiktok import TikTokConnector


class ConnectorFactory:
    """连接器工厂"""

    _connectors: Dict[str, Type[BaseConnector]] = {
        "meta": MetaConnector,
        "google": GoogleAdsConnector,
        "appsflyer": AppsFlyerConnector,
        "tiktok": TikTokConnector,    # TikTok for Business（真实 API 路径待接，当前 Mock 待命）
        "mock": MockMediaConnector,   # 有状态因果模拟媒体（替代被封的 Meta）
    }

    @classmethod
    def register(cls, platform: str, connector_class: Type[BaseConnector]):
        """注册新的连接器（支持插件扩展）"""
        cls._connectors[platform] = connector_class

    @classmethod
    def get_connector(cls,
                      platform: str,
                      db: Session,
                      app_id: int,
                      credentials: Dict,
                      execution_mode: str = "mock") -> Optional[BaseConnector]:
        """获取连接器实例。

        Phase 1.1：调用方必须显式声明 execution_mode（mock/sandbox/live）；
        不再由凭证/SDK 缺失静默切换到 mock。live 且不满足条件时构造函数会抛错。
        """
        connector_class = cls._connectors.get(platform.lower())
        if not connector_class:
            raise ValueError(f"Unknown connector platform: {platform}")

        return connector_class(db, app_id, credentials, execution_mode=execution_mode)

    @classmethod
    def available_connectors(cls) -> Dict[str, dict]:
        """获取可用的连接器列表及其信息"""
        result = {}
        for name, cls_ in cls._connectors.items():
            result[name] = {
                "platform": cls_.platform,
                "source_type": cls_.source_type,
                "rate_limit": cls_.rate_limit,
                "supported_modes": list(getattr(cls_, "supported_modes", ("mock",))),
                "capabilities": dict(getattr(cls_, "capabilities", {})),
            }
        return result


def resolve_credentials(platform: str, db=None, app_id: int = None) -> Dict[str, Any]:
    """解析连接器凭证：优先库表（connector_credentials，active+verified），回退 config google_*。

    Phase 1.1：仅负责取凭证，不再决定执行模式；调用方按 settings.agent_execution_mode 决定。
    """
    creds = None
    if db is not None and app_id is not None:
        try:
            from app.models.data import ConnectorCredential
            cred = db.query(ConnectorCredential).filter(
                ConnectorCredential.app_id == app_id,
                ConnectorCredential.platform == platform,
                ConnectorCredential.status == "active",
                ConnectorCredential.is_verified == True,
            ).order_by(ConnectorCredential.updated_at.desc()).first()
            if cred:
                creds = cred.credentials_json
        except Exception as e:
            logger.warning(f"resolve_credentials DB lookup failed: {e}")
    if not creds and platform == "google":
        from app.config import settings
        creds = settings.google_credentials_dict
    return creds or {}


__all__ = [
    "BaseConnector",
    "MetaConnector",
    "GoogleAdsConnector",
    "AppsFlyerConnector",
    "TikTokConnector",
    "MockMediaConnector",
    "ConnectorFactory",
]
