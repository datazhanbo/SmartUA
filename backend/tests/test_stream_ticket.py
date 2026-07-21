"""Phase 2.2 — SSE stream-ticket 单元测试。

覆盖 mint / consume / 单次消费 / 过期 / 跨 session 拒绝 / 清空后失效。
FastAPI 端到端断言留给 API smoke，本文件专注 store 语义正确性。
"""
import time
import pytest

from app.core.stream_ticket import StreamTicketStore, get_stream_ticket_store


def test_mint_and_consume_ok():
    store = StreamTicketStore(ttl_seconds=60)
    ticket, ttl = store.mint(user_id=42, session_id="sess-1")
    assert ttl == 60
    assert store.consume(ticket, "sess-1") == 42


def test_ticket_is_single_use():
    """消费一次后立即失效：防止 URL 泄漏 → 重放订阅。"""
    store = StreamTicketStore()
    ticket, _ = store.mint(user_id=1, session_id="s")
    assert store.consume(ticket, "s") == 1
    assert store.consume(ticket, "s") is None


def test_ticket_cross_session_rejected():
    """票据必须绑定到签发时的 session：换 session 一律拒绝。

    这是 Phase 2.1 对象授权的延续——即便攻击者拿到票据，也换不掉目标 session。
    """
    store = StreamTicketStore()
    ticket, _ = store.mint(user_id=1, session_id="s-real")
    assert store.consume(ticket, "s-other") is None
    # 错配后票据仍应失效（pop 已发生），原 session 也拿不到
    assert store.consume(ticket, "s-real") is None


def test_ticket_expires():
    """短期票据到期即失效。"""
    store = StreamTicketStore(ttl_seconds=1)
    ticket, _ = store.mint(user_id=1, session_id="s")
    time.sleep(1.1)
    assert store.consume(ticket, "s") is None


def test_empty_ticket_rejected():
    store = StreamTicketStore()
    assert store.consume("", "s") is None
    assert store.consume(None, "s") is None  # type: ignore[arg-type]


def test_unknown_ticket_rejected():
    store = StreamTicketStore()
    assert store.consume("does-not-exist", "s") is None


def test_singleton_is_reused():
    a = get_stream_ticket_store()
    b = get_stream_ticket_store()
    assert a is b


def test_clear_wipes_all_tickets():
    store = StreamTicketStore()
    t1, _ = store.mint(user_id=1, session_id="s1")
    t2, _ = store.mint(user_id=2, session_id="s2")
    store.clear()
    assert store.consume(t1, "s1") is None
    assert store.consume(t2, "s2") is None
