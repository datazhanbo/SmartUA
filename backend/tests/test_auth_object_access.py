"""Phase 2.1 — 对象级授权：跨 App 访问必须 404，同 App 授权用户放行。

用直连方式测试 `require_app_access` / `user_can_access_app` 与 agent 端点里的
`_require_session_access`：即便攻击者拿到别人 app 的 session_id，也拿不到内容。
"""
import pytest
from fastapi import HTTPException

from app.db.base import SessionLocal
from app.core.security import require_app_access, user_can_access_app
from app.models.sys import User, App, Role, UserAppBinding
from app.services.agent_runtime.session import get_session_store


def _bootstrap_users_and_apps(db):
    """在测试库里造 2 个用户 / 2 个 app / 只绑定 user1↔app1、user2↔app2。

    conftest 的 fixture 只清 agent 相关的表，不清 users/apps/roles，
    因此这里做幂等处理（存在则复用），避免 UNIQUE 冲突。
    """
    role = db.query(Role).filter(Role.name == "tester").first()
    if role is None:
        role = Role(name="tester", label="Tester")
        db.add(role); db.commit(); db.refresh(role)

    app1 = db.query(App).filter(App.app_key == "app1").first()
    if app1 is None:
        app1 = App(app_key="app1", app_name="App 1")
        db.add(app1); db.commit(); db.refresh(app1)
    app2 = db.query(App).filter(App.app_key == "app2").first()
    if app2 is None:
        app2 = App(app_key="app2", app_name="App 2")
        db.add(app2); db.commit(); db.refresh(app2)

    u1 = db.query(User).filter(User.email == "u1@test").first()
    if u1 is None:
        u1 = User(email="u1@test", username="u1", password_hash="x")
        db.add(u1); db.commit(); db.refresh(u1)
    u2 = db.query(User).filter(User.email == "u2@test").first()
    if u2 is None:
        u2 = User(email="u2@test", username="u2", password_hash="x")
        db.add(u2); db.commit(); db.refresh(u2)

    for uid, aid in [(u1.id, app1.id), (u2.id, app2.id)]:
        exists = db.query(UserAppBinding).filter(
            UserAppBinding.user_id == uid, UserAppBinding.app_id == aid).first()
        if exists is None:
            db.add(UserAppBinding(user_id=uid, app_id=aid, role_id=role.id))
    db.commit()
    return u1, u2, app1.id, app2.id


def test_user_can_access_own_app_but_not_other():
    db = SessionLocal()
    try:
        u1, u2, app1_id, app2_id = _bootstrap_users_and_apps(db)
        assert user_can_access_app(u1, app1_id, db) is True
        assert user_can_access_app(u1, app2_id, db) is False
        assert user_can_access_app(u2, app2_id, db) is True
        assert user_can_access_app(u2, app1_id, db) is False
    finally:
        db.close()


def test_require_app_access_raises_404_for_foreign_app():
    """Phase 2.1：跨 app 访问统一 404（不是 403），避免通过响应差异枚举 app_id。"""
    db = SessionLocal()
    try:
        u1, _u2, _app1_id, app2_id = _bootstrap_users_and_apps(db)
        with pytest.raises(HTTPException) as exc:
            require_app_access(u1, app2_id, db)
        assert exc.value.status_code == 404
    finally:
        db.close()


def test_require_session_access_blocks_cross_app_session():
    """跨 app 的 session_id 即便存在，也应表现为 404（授权先于存在性）。"""
    from app.api.v1.agent import _require_session_access
    db = SessionLocal()
    try:
        u1, u2, app1_id, app2_id = _bootstrap_users_and_apps(db)
        store = get_session_store()
        # u2 在 app2 里建的 session
        s = store.create(app_id=app2_id, user_id=u2.id, goal="foreign")
        store.persist(s)
        # u1 不属于 app2，不能读到该 session
        with pytest.raises(HTTPException) as exc:
            _require_session_access(s, u1, db)
        assert exc.value.status_code == 404
        # u2 自己可以
        _require_session_access(s, u2, db)  # 不抛
    finally:
        db.close()


def test_require_session_access_handles_none_session():
    """session 不存在与无权访问不可通过响应区分，都返回 404。"""
    from app.api.v1.agent import _require_session_access
    db = SessionLocal()
    try:
        u1, _u2, _a1, _a2 = _bootstrap_users_and_apps(db)
        with pytest.raises(HTTPException) as exc:
            _require_session_access(None, u1, db)
        assert exc.value.status_code == 404
    finally:
        db.close()
