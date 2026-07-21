"""Tests for EpisodicMemory: record, query, aggregate, persistence."""
import app.services.agent_runtime.memory as _memory_mod
from app.services.agent_runtime.memory import Episode, get_memory


def _reset_memory():
    _memory_mod._memory = None


def make_ep(action: str, roi_delta: float = 0.1, outcome: bool = True) -> Episode:
    return Episode(
        action=action,
        goal="test",
        params={"budget": 100},
        pre_state={"roi": 1.2},
        impact={"impact_24h": {"delta_roi": roi_delta, "delta_spend": 50}},
        outcome=outcome,
    )


def test_record_and_all():
    """record adds episode, all() returns all."""
    mem = get_memory()
    ep = make_ep("adjust_budget")
    mem.record(ep)
    all_eps = mem.all()
    assert len(all_eps) == 1
    assert all_eps[0].action == "adjust_budget"


def test_by_action():
    """by_action filters by action name."""
    mem = get_memory()
    mem.record(make_ep("pause_campaign"))
    mem.record(make_ep("adjust_budget"))
    mem.record(make_ep("pause_campaign"))

    pcs = mem.by_action("pause_campaign")
    assert len(pcs) == 2
    assert all(e.action == "pause_campaign" for e in pcs)


def test_has_experience():
    """has_experience returns True only for recorded actions."""
    mem = get_memory()
    assert not mem.has_experience("adjust_budget")
    mem.record(make_ep("adjust_budget"))
    assert mem.has_experience("adjust_budget")
    assert not mem.has_experience("nonexistent")


def test_recent():
    """recent returns latest N episodes."""
    mem = get_memory()
    for i in range(10):
        mem.record(make_ep(f"action_{i}"))
    recent = mem.recent(3)
    assert len(recent) == 3


def test_aggregate():
    """aggregate returns per-action stats with success_rate and avg_delta_roi."""
    mem = get_memory()
    mem.record(make_ep("adjust_budget", roi_delta=0.2, outcome=True))
    mem.record(make_ep("adjust_budget", roi_delta=0.1, outcome=True))
    mem.record(make_ep("adjust_budget", roi_delta=-0.1, outcome=False))
    mem.record(make_ep("pause_campaign", roi_delta=0.3, outcome=True))

    agg = mem.aggregate()
    assert "adjust_budget" in agg
    assert "pause_campaign" in agg
    ab = agg["adjust_budget"]
    assert ab["count"] == 3
    assert abs(ab["success_rate"] - 2 / 3) < 0.001
    # avg_delta_roi_24h = (0.2 + 0.1 + (-0.1)) / 3 = 0.0667
    assert abs(ab["avg_delta_roi_24h"] - 0.0667) < 0.01


def test_suggest_budget_increase_cap():
    """suggest_budget_increase_cap returns a positive number."""
    mem = get_memory()
    mem.record(make_ep("adjust_budget", roi_delta=0.2, outcome=True))
    cap = mem.suggest_budget_increase_cap()
    assert isinstance(cap, float)
    assert cap > 0


def test_persistence_after_reset():
    """Episodes survive singleton reset (DB-backed)."""
    mem = get_memory()
    mem.record(make_ep("persist_action"))

    _reset_memory()
    eps = get_memory().by_action("persist_action")
    assert len(eps) == 1
    assert eps[0].action == "persist_action"


def test_clear():
    """clear removes all episodes from cache and DB."""
    mem = get_memory()
    mem.record(make_ep("temp_action"))
    assert len(mem.all()) == 1

    mem.clear()
    assert len(mem.all()) == 0

    _reset_memory()
    assert len(get_memory().all()) == 0