"""Tests for AnomalyDetector: creative fatigue, ROI drop, disabled account.

Uses MockMediaConnector (simulation engine) so no external credentials needed.
"""
from app.services.agent_runtime.autonomy import AnomalyDetector, AutonomyEngine
from app.services.agent_runtime.strategy import get_strategy
from app.services.connectors.mock_media import (
    MockMediaConnector, reset_sim_engine, get_sim_engine,
)
from app.config import settings


def _make_connector(**kw) -> MockMediaConnector:
    return MockMediaConnector(db=None, app_id=1, credentials={"seed": 42}, execution_mode="mock")


def test_detector_fresh_engine():
    """Freshly seeded engine detects low ROI but not creative fatigue."""
    reset_sim_engine(seed=42)
    connector = _make_connector()
    detector = AnomalyDetector(strategy=get_strategy())
    anomalies = detector.detect(connector, app_id=1)
    assert any(a.type == "roi_drop" for a in anomalies)
    assert not any(a.type == "creative_fatigue" for a in anomalies)


def test_detector_creative_fatigue():
    """Engine advanced 12 days should trigger creative_fatigue anomalies."""
    eng = reset_sim_engine(seed=42)
    eng.advance_days(12)
    connector = _make_connector()
    detector = AnomalyDetector(strategy=get_strategy())
    anomalies = detector.detect(connector, app_id=1)
    fatigue = [a for a in anomalies if a.type == "creative_fatigue"]
    assert len(fatigue) > 0, (
        f"Expected creative_fatigue anomalies, got {[a.type for a in anomalies]}"
    )
    for a in fatigue:
        assert a.severity == "info"
        assert a.suggested_risk == "L0"


def test_detector_disabled_account():
    """Disabled account triggers ACCOUNT_DISABLED anomaly."""
    reset_sim_engine(seed=42)
    get_sim_engine().set_account_status("DISABLED")
    connector = _make_connector()
    detector = AnomalyDetector(strategy=get_strategy())
    anomalies = detector.detect(connector, app_id=1)
    disabled = [a for a in anomalies if a.type == "account_disabled"]
    assert len(disabled) > 0
    assert disabled[0].severity == "critical"
    # Clean up
    get_sim_engine().set_account_status("ok")


def test_detector_roi_drop():
    """Seeded low-ROI campaign triggers roi_drop."""
    eng = reset_sim_engine(seed=42)
    eng.advance_days(12)
    connector = _make_connector()
    detector = AnomalyDetector(strategy=get_strategy())
    anomalies = detector.detect(connector, app_id=1)
    roi_drops = [a for a in anomalies if a.type == "roi_drop"]
    assert len(roi_drops) > 0
    assert all(a.suggested_risk == "L1" for a in roi_drops)


def test_autonomy_engine_scan():
    """AutonomyEngine.scan produces alerts including auto-executed fatigue."""
    eng = reset_sim_engine(seed=42)
    eng.advance_days(12)
    platform_backup = settings.agent_default_platform
    settings.agent_default_platform = "mock"
    try:
        alerts = AutonomyEngine().scan(app_id=1)
        # Should have at least creative fatigue alerts
        assert len(alerts) > 0
        statuses = {a.status for a in alerts}
        assert "auto_executed" in statuses or "pending_approval" in statuses
    finally:
        settings.agent_default_platform = platform_backup