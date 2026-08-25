"""Phase 3.3 —— 动作派发 + 回读验证（同步 dispatcher，落进 AgentActionStore 状态机）。

Loop 审批通过后不再直接调用 tool.handler；改为：

    action = store.mint_or_get(db, req)          # 唯一动作实体（幂等）
    store.transition(db, action, "approved")     # 记录批准时刻
    dispatcher.dispatch_and_verify(action, ...)  # 走状态机：dispatching → accepted → verified

关键不变量（与 Phase 3.1 状态机契约一致）：

1. **同一 idempotency_key 只对媒体调用一次**：重复入队直接返回 verified/failed 的既有动作。
2. **dispatching 出错分两类**：
   - 抛异常 / 超时 / 明确不确定 → `unknown`，等对账（reconcile）收敛，不重试媒体。
   - 明确失败（provider 返回 success=False） → `failed`。
3. **accepted → verified 之间调 `connector.read_state(entity_id)` 做回读**：
   - 状态回读能匹配预期 → `verified`。
   - 状态不匹配、或读不到 → `unknown`（媒体可能生效但对账数据尚未落地）。
4. **不改现有审计链**：`IntentExecution` / `ActionLog` 仍由 `_write()` 写；新的 `action.intent_execution_id`/`action_log_id` 只在软链接层记录。

Phase 3.3 保留同步落库，不引入 outbox 表。真正的 durable outbox + 独立 worker
留给 Phase 5.2，届时 dispatcher 会被 worker 消费而非 Loop 直接调。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.agent_runtime import AgentActionDB
from app.services.agent_runtime.action_store import (
    ActionRequest, AgentActionStore, InvalidTransition, get_action_store,
)

logger = logging.getLogger(__name__)


@dataclass
class DispatchOutcome:
    """派发 + 回读一次的最终结果，供 Loop 组装 ACTION 步骤。"""
    action: AgentActionDB
    state: str                              # verified / failed / unknown
    provider_response: Optional[Dict[str, Any]] = None
    observation: str = ""                   # 人类可读描述


# 判定 dispatch 结果的钩子：默认认为 result.get("success") is True 即媒体接受。
# 真实 Connector 有更复杂的 success/pending/rejected 语义时可以传自定义 judge。
def _default_judge(result: Any) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """返回 (state_after_dispatch, provider_response, error)。

    - success=True  → accepted（后续再走 verify）。
    - success=False → failed（媒体明确拒绝，不进入 unknown）。
    - result 非 dict / 缺 success → unknown（拿不到明确信号，交对账）。
    """
    if not isinstance(result, dict):
        return "unknown", None, f"non-dict result: {type(result).__name__}"
    if result.get("success") is True:
        return "accepted", result, None
    if result.get("success") is False:
        return "failed", result, str(result.get("error") or "provider rejected")
    return "unknown", result, "provider returned without explicit success flag"


def _verify_state(current: Optional[Dict[str, Any]], req: ActionRequest) -> Tuple[bool, str]:
    """回读后判定动作是否已生效。返回 (matched, reason)。

    覆盖 Loop 目前会派发的写工具：
    - `update_campaign_status` / `update_adset_status` → 期望 status == req.request["status"]
    - `update_campaign_budget` → 期望 daily_budget ≈ req.request["daily_budget"]（相对差 ≤ 5%）
    - `update_adset_bid` / `rotate_creative` → 无直接可读字段 → 有 state 即认为 verified
    """
    if current is None:
        return False, "read_state returned None"
    action = req.action
    if action in ("update_campaign_status", "update_adset_status"):
        expected = str(req.request.get("status", "")).upper()
        got = str(current.get("status", "")).upper()
        return (expected == got, f"status expected={expected} got={got}")
    if action == "update_campaign_budget":
        try:
            expected = float(req.request.get("daily_budget", 0))
        except (TypeError, ValueError):
            return False, "request.daily_budget not numeric"
        got_raw = current.get("daily_budget")
        if got_raw is None:
            return False, "current.daily_budget missing"
        try:
            got = float(got_raw)
        except (TypeError, ValueError):
            return False, "current.daily_budget not numeric"
        if expected == 0:
            return got == 0, f"daily_budget expected=0 got={got}"
        rel = abs(got - expected) / abs(expected)
        return (rel <= 0.05, f"daily_budget expected={expected:.2f} got={got:.2f} rel={rel:.3f}")
    # 无法从 current_summary/read_state 直接读回的动作（bid / rotate）：只要 read_state 不为空
    # 就认为 accepted 已经落到目标账户，等 Phase 4 的延迟回采再做归因验证。
    return True, f"no field-level verify for {action}; accepted"


class Dispatcher:
    """同步派发器：把"审批通过的动作"经状态机推进到 verified/failed/unknown。

    调用方（Loop）负责持有 `db` session；本类不 commit 也不 rollback，交回上游控制事务。
    """

    def __init__(self, store: Optional[AgentActionStore] = None):
        self._store = store or get_action_store()

    def dispatch_and_verify(
        self,
        db: Session,
        req: ActionRequest,
        media_call: Callable[[], Any],
        read_state: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        judge: Callable[[Any], Tuple[str, Optional[Dict[str, Any]], Optional[str]]] = _default_judge,
        intent_execution_id: Optional[int] = None,
        action_log_id: Optional[int] = None,
    ) -> DispatchOutcome:
        """完整走一次：mint → approved → dispatching → media_call → accepted → verify → verified.

        - `media_call`：无参 callable，返回媒体 API 结果（通常是 `connector.apply_action(...)` 的返回）。
        - `read_state`：`entity_id → dict | None`。默认无（等价于"跳过 verify，直接从 accepted 停在
          verified 或 unknown 视 judge 而定"），但 Loop 会传 `ctx.connector.read_state` 让 mock/live
          走真实回读路径。
        """
        action = self._store.mint_or_get(db, req)

        # 幂等短路：已经处在终态 / 已经 verified 过 → 直接返回既有状态，不再叫媒体。
        if action.state in ("verified", "failed"):
            return DispatchOutcome(
                action=action, state=action.state,
                provider_response=action.provider_response_json,
                observation=f"idempotent: action {action.id} already {action.state}",
            )

        # proposed → approved（若已经 approved 则跳过，允许幂等重试）
        if action.state == "proposed":
            self._store.transition(db, action, "approved",
                                    intent_execution_id=intent_execution_id,
                                    action_log_id=action_log_id)
        elif action.state == "approved":
            # 幂等：软链接可能后到，允许 override
            if intent_execution_id is not None:
                action.intent_execution_id = intent_execution_id
            if action_log_id is not None:
                action.action_log_id = action_log_id

        # approved → dispatching
        try:
            self._store.transition(db, action, "dispatching")
        except InvalidTransition:
            # 例如已经被并发推进过一轮 —— 直接返回当前状态
            return DispatchOutcome(action=action, state=action.state,
                                    provider_response=action.provider_response_json,
                                    observation=f"skipped dispatch: current state={action.state}")

        # 真正调媒体
        try:
            result = media_call()
        except Exception as e:
            logger.exception("dispatcher media_call raised")
            try:
                self._store.transition(db, action, "unknown", error=f"media call raised: {e}")
            except InvalidTransition:
                pass
            return DispatchOutcome(action=action, state="unknown",
                                    provider_response=None,
                                    observation=f"media call raised: {e}")

        state_after, provider_response, err = judge(result)
        provider_request_id = None
        if isinstance(provider_response, dict):
            provider_request_id = (provider_response.get("provider_request_id")
                                    or provider_response.get("request_id"))

        if state_after == "failed":
            self._store.transition(db, action, "failed",
                                    provider_request_id=provider_request_id,
                                    provider_response=provider_response,
                                    error=err)
            return DispatchOutcome(action=action, state="failed",
                                    provider_response=provider_response,
                                    observation=err or "provider rejected")

        if state_after == "unknown":
            self._store.transition(db, action, "unknown",
                                    provider_request_id=provider_request_id,
                                    provider_response=provider_response,
                                    error=err)
            return DispatchOutcome(action=action, state="unknown",
                                    provider_response=provider_response,
                                    observation=err or "provider response ambiguous")

        # state_after == "accepted"
        self._store.transition(db, action, "accepted",
                                provider_request_id=provider_request_id,
                                provider_response=provider_response)

        # accepted → verified via read_state（找不到就停在 unknown）
        outcome = self._verify(db, action, req, read_state, provider_response)
        return outcome

    def _verify(self,
                db: Session,
                action: AgentActionDB,
                req: ActionRequest,
                read_state: Optional[Callable[[str], Optional[Dict[str, Any]]]],
                provider_response: Optional[Dict[str, Any]]) -> DispatchOutcome:
        if read_state is None or not req.entity_id:
            # 无回读能力：Phase 3.3 保守停在 accepted / 未 verified 之间 —— 用 unknown 让下游
            # 对账循环挑起。真实 Connector 会实现 read_state；这条路径只在测试或未实现连接器出现。
            try:
                self._store.transition(db, action, "unknown",
                                        error="no read_state provided for verify")
            except InvalidTransition:
                pass
            return DispatchOutcome(action=action, state="unknown",
                                    provider_response=provider_response,
                                    observation="accepted but no read_state to verify")

        try:
            current = read_state(req.entity_id)
        except Exception as e:
            logger.warning("read_state raised for entity %s: %s", req.entity_id, e)
            current = None

        matched, reason = _verify_state(current, req)
        if matched:
            self._store.transition(db, action, "verified")
            _enqueue_impact_jobs(db, action)
            return DispatchOutcome(action=action, state="verified",
                                    provider_response=provider_response,
                                    observation=f"verified: {reason}")
        # 回读到了状态但和预期不匹配 —— unknown，等 reconcile 再收敛（不 fail：可能存在延迟）
        try:
            self._store.transition(db, action, "unknown", error=f"verify mismatch: {reason}")
        except InvalidTransition:
            pass
        return DispatchOutcome(action=action, state="unknown",
                                provider_response=provider_response,
                                observation=f"verify mismatch: {reason}")

    def reconcile(
        self,
        db: Session,
        action: AgentActionDB,
        req: ActionRequest,
        read_state: Callable[[str], Optional[Dict[str, Any]]],
    ) -> DispatchOutcome:
        """对账入口：把 `unknown` 动作再拉一次媒体状态，看能否收敛到 verified/failed。

        - 只处理当前状态是 `unknown` 的动作；其他状态直接返回。
        - 读到的状态匹配 → verified；显式不匹配（如 status 完全反过来）→ failed。
        - 依然读不到 → 保持 unknown，等下一次对账。
        """
        if action.state != "unknown":
            return DispatchOutcome(action=action, state=action.state,
                                    provider_response=action.provider_response_json,
                                    observation=f"reconcile skipped: state={action.state}")
        try:
            current = read_state(req.entity_id) if req.entity_id else None
        except Exception as e:
            logger.warning("reconcile read_state raised: %s", e)
            current = None

        if current is None:
            return DispatchOutcome(action=action, state="unknown",
                                    provider_response=action.provider_response_json,
                                    observation="reconcile: read_state still None")

        matched, reason = _verify_state(current, req)
        if matched:
            self._store.transition(db, action, "verified")
            _enqueue_impact_jobs(db, action)
            return DispatchOutcome(action=action, state="verified",
                                    provider_response=action.provider_response_json,
                                    observation=f"reconciled → verified: {reason}")
        # 状态明确不同 → 认为媒体最终失败，收敛为 failed
        try:
            self._store.transition(db, action, "failed",
                                    error=f"reconcile mismatch: {reason}")
        except InvalidTransition:
            pass
        return DispatchOutcome(action=action, state=action.state,
                                provider_response=action.provider_response_json,
                                observation=f"reconciled → {action.state}: {reason}")


_dispatcher: Optional[Dispatcher] = None


def _enqueue_impact_jobs(db: Session, action: AgentActionDB) -> None:
    """Phase 4.2 —— 动作 verified 后 enqueue observed/attributed × 2h/24h/7d 六条 job。

    失败不影响主 dispatcher 流程（Loop 已 commit 了 verified 状态）。
    """
    try:
        from app.services.agent_runtime.impact_collector import enqueue_after_verified
        enqueue_after_verified(db, action)
    except Exception as e:
        logger.warning("enqueue impact jobs for action %s failed: %s", action.id, e)


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
    return _dispatcher
