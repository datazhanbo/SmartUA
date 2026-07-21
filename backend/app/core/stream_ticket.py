"""Phase 2.2 — SSE stream-ticket 存储。

设计目标：把长期 JWT 从 SSE URL / 代理日志 / 浏览器历史里彻底移出。前端先用 JWT
调用 `POST /agent/sessions/{id}/stream-ticket` 换一个短期、单次、绑定 (user, session)
的票据，再拿它开 EventSource。票据泄露的攻击面从"整份 JWT"缩到"一次订阅"。

约束：
- 单次消费：`consume()` 成功后立即失效，重放拿不到第二次订阅。
- 绑定实体：ticket → (user_id, session_id)，跨 session 或跨 user 的错配一律拒绝。
- 短生存：默认 60s；服务重启后进程内票据一并失效（这正是我们要的语义）。

存储放在进程内 dict 是刻意选择——票据本就短命且不能跨副本共享（换 session
换 ticket），把它塞进 SQLite/Redis 反而引入不必要的耦合。多副本部署下每副本
自建票据即可（Phase 5 durable runtime 前的临时形态）。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class _Ticket:
    user_id: int
    session_id: str
    expires_at: float


class StreamTicketStore:
    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._tickets: Dict[str, _Ticket] = {}

    def mint(self, user_id: int, session_id: str,
             ttl_seconds: Optional[int] = None) -> tuple[str, int]:
        ttl = int(ttl_seconds or self._ttl)
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._prune_locked()
            self._tickets[token] = _Ticket(
                user_id=user_id, session_id=session_id,
                expires_at=time.time() + ttl,
            )
        return token, ttl

    def consume(self, ticket: str, session_id: str) -> Optional[int]:
        """消费一次票据；返回持有者 user_id，失败返回 None。

        触发失败的所有原因（不存在 / 过期 / 已消费 / session 不匹配）都返回 None，
        对调用方不透露具体原因，避免侧信道。
        """
        if not ticket:
            return None
        with self._lock:
            row = self._tickets.pop(ticket, None)  # pop = 单次消费
            if row is None:
                return None
            if row.expires_at < time.time():
                return None
            if row.session_id != session_id:
                # session 错配：即便票据合法也不放行；已经 pop 了，天然拒绝重放
                return None
            return row.user_id

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [k for k, v in self._tickets.items() if v.expires_at < now]
        for k in expired:
            self._tickets.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()


_store: Optional[StreamTicketStore] = None


def get_stream_ticket_store() -> StreamTicketStore:
    global _store
    if _store is None:
        from app.config import settings
        _store = StreamTicketStore(
            ttl_seconds=int(getattr(settings, "agent_sse_ticket_ttl_seconds", 60)))
    return _store
