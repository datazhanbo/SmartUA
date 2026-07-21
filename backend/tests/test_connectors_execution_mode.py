"""Phase 1.1: connector execution_mode + fail-closed + provenance tests."""
import pytest

from app.services.connectors import ConnectorFactory
from app.services.connectors.google import GoogleAdsConnector
from app.services.connectors.meta import MetaConnector
from app.services.connectors.tiktok import TikTokConnector
from app.services.connectors.appsflyer import AppsFlyerConnector
from app.services.connectors.mock_media import MockMediaConnector


# ---------- supported_modes / capabilities 声明 ----------

def test_google_supports_mock_and_live():
    assert set(GoogleAdsConnector.supported_modes) == {"mock", "live"}
    assert GoogleAdsConnector.capabilities["read"] is True
    assert GoogleAdsConnector.capabilities["write"] is True


def test_meta_supports_mock_and_live():
    assert set(MetaConnector.supported_modes) == {"mock", "live"}


def test_tiktok_mock_only():
    assert set(TikTokConnector.supported_modes) == {"mock"}


def test_appsflyer_mock_only():
    assert set(AppsFlyerConnector.supported_modes) == {"mock"}


def test_mock_media_mock_only():
    assert set(MockMediaConnector.supported_modes) == {"mock"}


# ---------- 拒绝不支持的执行模式 ----------

def test_google_sandbox_rejected():
    with pytest.raises(ValueError, match="不支持执行模式"):
        GoogleAdsConnector(db=None, app_id=1, credentials={}, execution_mode="sandbox")


def test_tiktok_live_rejected():
    with pytest.raises(ValueError, match="不支持执行模式"):
        TikTokConnector(db=None, app_id=1, credentials={}, execution_mode="live")


def test_appsflyer_live_rejected():
    with pytest.raises(ValueError, match="不支持执行模式"):
        AppsFlyerConnector(db=None, app_id=1, credentials={}, execution_mode="live")


# ---------- Google live fail-closed ----------

def test_google_live_missing_credentials_fail_closed():
    with pytest.raises(ValueError, match="缺少凭证字段"):
        GoogleAdsConnector(db=None, app_id=1, credentials={}, execution_mode="live")


def test_google_live_incomplete_credentials_fail_closed():
    partial = {
        "client_id": "cid",
        "client_secret": "sec",
        # 缺 refresh_token/developer_token/customer_id
    }
    with pytest.raises(ValueError, match="缺少凭证字段"):
        GoogleAdsConnector(db=None, app_id=1, credentials=partial, execution_mode="live")


def test_google_live_missing_sdk_fail_closed(monkeypatch):
    full = {
        "client_id": "cid",
        "client_secret": "sec",
        "refresh_token": "ref",
        "developer_token": "dev",
        "customer_id": "1234567890",
    }
    monkeypatch.setattr(GoogleAdsConnector, "_sdk_available", staticmethod(lambda: False))
    # 凭证齐全但 SDK 不可用 → 必须抛错，绝不回退 mock
    with pytest.raises(RuntimeError, match="google-ads SDK"):
        GoogleAdsConnector(db=None, app_id=1, credentials=full, execution_mode="live")


# ---------- Meta live fail-closed ----------

def test_meta_live_missing_sdk_or_token_fail_closed(monkeypatch):
    import app.services.connectors.meta as meta_mod
    monkeypatch.setattr(meta_mod, "FACEBOOK_SDK_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="facebook_business SDK"):
        MetaConnector(db=None, app_id=1, credentials={"access_token": "t"}, execution_mode="live")

    monkeypatch.setattr(meta_mod, "FACEBOOK_SDK_AVAILABLE", True)
    with pytest.raises(ValueError, match="access_token"):
        MetaConnector(db=None, app_id=1, credentials={}, execution_mode="live")


# ---------- Mock 结果 provenance ----------

def test_mock_connector_result_meta():
    conn = MockMediaConnector(db=None, app_id=1, credentials={"seed": 1}, execution_mode="mock")
    meta = conn._result_meta()
    assert meta["platform"] == "mock"
    assert meta["execution_mode"] == "mock"
    assert meta["is_mock"] is True
    assert "verified_at" in meta and meta["verified_at"].endswith("Z")
    assert meta["account_id"] == "mock-sim-account"


def test_action_result_provenance_decoration():
    conn = MockMediaConnector(db=None, app_id=1, credentials={"seed": 1}, execution_mode="mock")
    # apply_action -> update_campaign_status 会经过 _decorate_action_result
    res = conn.apply_action("update_campaign_status", "camp_1", status="PAUSED")
    assert res.get("execution_mode") == "mock"
    assert res.get("platform") == "mock"
    assert res.get("is_mock") is True
    assert "verified_at" in res


# ---------- Google mock 路径仍可读写 ----------

def test_google_mock_construct_ok():
    conn = GoogleAdsConnector(db=None, app_id=1, credentials={}, execution_mode="mock")
    assert conn.execution_mode == "mock"
    assert conn._is_mock is True
    assert conn.auth() is True


# ---------- 工厂 metadata 暴露 supported_modes/capabilities ----------

def test_factory_metadata_exposes_modes_and_capabilities():
    avail = ConnectorFactory.available_connectors()
    for name in ("mock", "google", "meta", "tiktok", "appsflyer"):
        info = avail[name]
        assert isinstance(info["supported_modes"], list)
        assert isinstance(info["capabilities"], dict)
