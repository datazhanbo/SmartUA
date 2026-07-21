"""Tests for ConnectorFactory registration and mock connector behavior."""
from app.services.connectors import ConnectorFactory
from app.services.connectors.base import BaseConnector
from app.services.connectors.mock_media import MockMediaConnector


def test_registered_platforms():
    """ConnectorFactory should contain expected platforms."""
    available = ConnectorFactory.available_connectors()
    assert "mock" in available
    assert "meta" in available
    assert "google" in available
    assert "tiktok" in available
    assert "appsflyer" in available


def test_get_connector_mock():
    """get_connector with 'mock' returns a MockMediaConnector."""
    conn = ConnectorFactory.get_connector("mock", db=None, app_id=1, credentials={}, execution_mode="mock")
    assert isinstance(conn, MockMediaConnector)
    assert conn.platform == "mock"
    assert conn.execution_mode == "mock"
    assert conn.auth() is True


def test_get_connector_unknown_raises():
    """get_connector with unknown platform raises ValueError."""
    import pytest
    with pytest.raises(ValueError, match="Unknown connector platform"):
        ConnectorFactory.get_connector("nonexistent", db=None, app_id=1, credentials={}, execution_mode="mock")


def test_register_new_platform():
    """register adds a new connector class."""
    class CustomConnector(BaseConnector):
        platform = "custom"
        source_type = "media"
        rate_limit = 10
        supported_modes = ("mock",)
        def auth(self): return True
        def pull(self, *a, **kw): return {"raw_rows": [], "metadata": {}}
        def normalize(self, r): return r

    ConnectorFactory.register("custom", CustomConnector)
    available = ConnectorFactory.available_connectors()
    assert "custom" in available
    conn = ConnectorFactory.get_connector("custom", db=None, app_id=1, credentials={}, execution_mode="mock")
    assert isinstance(conn, CustomConnector)


def test_available_connectors_structure():
    """available_connectors returns dict with platform/source_type/rate_limit/supported_modes/capabilities."""
    avail = ConnectorFactory.available_connectors()
    for name, info in avail.items():
        assert "platform" in info
        assert "source_type" in info
        assert "rate_limit" in info
        assert "supported_modes" in info
        assert isinstance(info["supported_modes"], list)
        assert "capabilities" in info
        assert info["platform"] == name