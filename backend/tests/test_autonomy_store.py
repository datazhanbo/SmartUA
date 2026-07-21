"""Tests for AutonomyStore: alert CRUD, cooldown dedup, persistence."""
import app.services.agent_runtime.autonomy as _autonomy_mod
from app.services.agent_runtime.autonomy import (
    Anomaly, AutonomyAlert, get_autonomy_store, AutonomyStore,
)


def _reset_autonomy_store():
    _autonomy_mod._autonomy_store = None


def make_anomaly(app_id: int = 1, type_: str = "roi_drop",
                 title: str = "Test anomaly", campaign_id: str = "c1") -> Anomaly:
    return Anomaly(app_id=app_id, type=type_, title=title, campaign_id=campaign_id)


def make_alert(app_id: int = 1, anomaly: Anomaly = None,
               status: str = "pending_approval") -> AutonomyAlert:
    if anomaly is None:
        anomaly = make_anomaly()
    return AutonomyAlert(app_id=app_id, anomaly=anomaly, status=status)


def test_add_and_list():
    """add_alert adds to store, list_alerts returns all."""
    store = get_autonomy_store()
    al = make_alert()
    store.add_alert(al)
    alerts = store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0].id == al.id
    assert alerts[0].status == "pending_approval"
    assert alerts[0].anomaly.title == "Test anomaly"


def test_list_by_app_id():
    """list_alerts filters by app_id."""
    store = get_autonomy_store()
    store.add_alert(make_alert(app_id=1))
    store.add_alert(make_alert(app_id=2))
    assert len(store.list_alerts(app_id=1)) == 1
    assert len(store.list_alerts(app_id=2)) == 1
    assert len(store.list_alerts()) == 2


def test_get_alert():
    """get_alert returns alert by id."""
    store = get_autonomy_store()
    al = make_alert()
    store.add_alert(al)
    fetched = store.get_alert(al.id)
    assert fetched is not None
    assert fetched.id == al.id
    assert store.get_alert("nonexistent") is None


def test_pending_count():
    """pending_count returns number of pending_approval alerts."""
    store = get_autonomy_store()
    assert store.pending_count() == 0
    store.add_alert(make_alert(status="pending_approval"))
    store.add_alert(make_alert(status="pending_approval"))
    store.add_alert(make_alert(status="auto_executed"))
    assert store.pending_count() == 2


def test_cooldown():
    """should_skip returns True for recently handled anomalies."""
    store = get_autonomy_store()
    an = make_anomaly()
    seq = store.next_seq()

    # Not yet handled → should not skip
    assert not store.should_skip(an, seq)

    # Mark handled → should skip for next few scans
    store.mark_handled(an, seq)
    assert store.should_skip(an, seq + 1)

    # Beyond cooldown window → should not skip
    assert not store.should_skip(an, seq + 100)


def test_cooldown_different_anomalies():
    """Different anomaly types are not affected by each other's cooldown."""
    store = get_autonomy_store()
    an1 = make_anomaly(type_="roi_drop", campaign_id="c1")
    an2 = make_anomaly(type_="creative_fatigue", campaign_id="c2")
    seq = store.next_seq()

    store.mark_handled(an1, seq)
    assert store.should_skip(an1, seq + 1)
    assert not store.should_skip(an2, seq + 1)  # Different anomaly


def test_persistence_after_reset():
    """Alerts survive singleton reset (DB-backed)."""
    store = get_autonomy_store()
    al = make_alert()
    store.add_alert(al)

    _reset_autonomy_store()
    loaded = get_autonomy_store().get_alert(al.id)
    assert loaded is not None
    assert loaded.status == "pending_approval"
    assert loaded.anomaly.title == "Test anomaly"


def test_clear():
    """clear removes all alerts."""
    store = get_autonomy_store()
    store.add_alert(make_alert())
    assert len(store.list_alerts()) == 1

    store.clear()
    assert len(store.list_alerts()) == 0

    _reset_autonomy_store()
    assert len(get_autonomy_store().list_alerts()) == 0