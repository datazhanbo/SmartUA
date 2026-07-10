from typing import Dict, Type, Optional
from sqlalchemy.orm import Session

from .base import BaseConnector
from .meta import MetaConnector
from .google import GoogleAdsConnector
from .appsflyer import AppsFlyerConnector
from .mock_media import MockMediaConnector


class ConnectorFactory:
    """连接器工厂"""

    _connectors: Dict[str, Type[BaseConnector]] = {
        "meta": MetaConnector,
        "google": GoogleAdsConnector,
        "appsflyer": AppsFlyerConnector,
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
                      credentials: Dict) -> Optional[BaseConnector]:
        """获取连接器实例"""
        connector_class = cls._connectors.get(platform.lower())
        if not connector_class:
            raise ValueError(f"Unknown connector platform: {platform}")

        return connector_class(db, app_id, credentials)

    @classmethod
    def available_connectors(cls) -> Dict[str, dict]:
        """获取可用的连接器列表及其信息"""
        result = {}
        for name, cls_ in cls._connectors.items():
            result[name] = {
                "platform": cls_.platform,
                "source_type": cls_.source_type,
                "rate_limit": cls_.rate_limit,
            }
        return result


__all__ = [
    "BaseConnector",
    "MetaConnector",
    "GoogleAdsConnector",
    "AppsFlyerConnector",
    "MockMediaConnector",
    "ConnectorFactory",
]
