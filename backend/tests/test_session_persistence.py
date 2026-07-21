"""Tests for AgentSessionStore: CRUD, persistence across singleton reset."""
import app.services.agent_runtime.session as _session_mod
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)


def _reset_session_store():
    _session_mod._session_store = None


def test_create_session():
    """create returns a session with correct fields."""
    store = get_session_store()
    s = store.create(app_id=1, user_id=42, goal="test-goal")
    assert s.id is not None
    assert s.app_id == 1
    assert s.user_id == 42
    assert s.goal == "test-goal"
    assert s.status == "running"
    assert len(s.steps) == 0


def test_persist_and_reload():
    """Session persisted to DB can be reloaded after singleton reset."""
    store = get_session_store()
    s = store.create(app_id=1, user_id=1, goal="persist-goal")
    s.add_step(AgentStep(kind=AgentStepKind.THOUGHT, text="step1"))
    s.add_step(AgentStep(kind=AgentStepKind.ACTION, text="step2", tool="test_tool"))
    s.status = "done"
    store.persist(s)
    sid = s.id

    _reset_session_store()
    loaded = get_session_store().get(sid)
    assert loaded is not None
    assert loaded.status == "done"
    assert loaded.goal == "persist-goal"
    assert len(loaded.steps) == 2
    assert loaded.steps[0].kind == "thought"
    assert loaded.steps[1].tool == "test_tool"


def test_list_by_app_id():
    """list filters sessions by app_id."""
    store = get_session_store()
    s1 = store.create(app_id=1, user_id=1, goal="g1")
    store.persist(s1)
    s2 = store.create(app_id=2, user_id=1, goal="g2")
    store.persist(s2)
    s3 = store.create(app_id=1, user_id=2, goal="g3")
    store.persist(s3)

    app1_sessions = store.list(app_id=1)
    assert len(app1_sessions) == 2
    assert all(s.app_id == 1 for s in app1_sessions)


def test_delete():
    """delete removes session from cache and DB."""
    store = get_session_store()
    s = store.create(app_id=1, user_id=1, goal="delete-me")
    store.persist(s)
    sid = s.id

    assert store.delete(sid) is True
    assert store.get(sid) is None

    _reset_session_store()
    assert get_session_store().get(sid) is None


def test_delete_nonexistent():
    """delete returns False for unknown session."""
    store = get_session_store()
    assert store.delete("nonexistent") is False


def test_clear():
    """clear removes all sessions."""
    store = get_session_store()
    s1 = store.create(app_id=1, user_id=1, goal="g1")
    s2 = store.create(app_id=1, user_id=1, goal="g2")
    store.persist(s1)
    store.persist(s2)

    store.clear()
    assert len(store.list(app_id=1)) == 0

    _reset_session_store()
    assert len(get_session_store().list(app_id=1)) == 0


def test_session_provenance_persists_across_reload():
    """Phase 1.2: platform / execution_mode / account_id must survive DB reload."""
    store = get_session_store()
    s = store.create(
        app_id=1, user_id=1, goal="prov-goal",
        platform="mock", execution_mode="mock", account_id="mock-sim-account",
    )
    store.persist(s)
    sid = s.id

    _reset_session_store()
    loaded = get_session_store().get(sid)
    assert loaded is not None
    assert loaded.platform == "mock"
    assert loaded.execution_mode == "mock"
    assert loaded.account_id == "mock-sim-account"
    # Provenance 存进 context_json 的保留键，但对外 context 不能泄露
    assert "_provenance" not in loaded.context


def test_session_provenance_defaults_are_none():
    """未显式传入 provenance 时对外表现为 None，不能把内部保留键泄露到 context。"""
    store = get_session_store()
    s = store.create(app_id=1, user_id=1, goal="no-prov")
    store.persist(s)
    _reset_session_store()
    loaded = get_session_store().get(s.id)
    assert loaded is not None
    assert loaded.platform is None
    assert loaded.execution_mode is None
    assert loaded.account_id is None
    assert "_provenance" not in loaded.context