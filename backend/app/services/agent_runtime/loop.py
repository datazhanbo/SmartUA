"""Agent Loop —— 从"单轮解析"升级为"规划 + ReAct + 多轮 + 人在环"。

循环：`think → select tool → (execute | propose) → observe → think again`，
直到目标达成 / 需人确认 / 达最大步数。

两种决策来源（与项目"LLM 解耦 + 优雅降级"原则一致）：
- LLM 规划：有可用 LLM 时，把工具清单 + 目标 + 上下文喂给路由引擎，解析其返回的
  `{"action","params"}` 或 `{"final_answer"}`。
- 规则引擎兜底：无 LLM 时（如本环境无 API Key），用确定性规划器把模糊目标拆成多步。

安全护栏：写工具 L1/L2 只"提议"，由 Agent Loop 转为人在环审批；
LLM 不替人做审批判断。L0（如换素材）自动执行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)
from app.services.agent_runtime.tools import (
    AgentContext, get_tool_registry, TOOL_TO_ACTION,
)

logger = logging.getLogger(__name__)


# Phase 3.2：审批过期 / 状态漂移
#
# 提案冻结 (expires_at, snapshot)；审批通过后 Loop 会：
#   1. 若 now > expires_at → 拒绝执行、给出观察、重新规划。
#   2. 重新读取实体：roi / spend / daily_budget 相对快照的相对变化超过 drift_pct，
#      或 status 从快照直接翻转 → 拒绝执行、给出漂移说明、重新规划。
# 目的是避免"等待期间账户状态已变（预算调过、活动被暂停、ROI 塌方），审批却还照旧执行旧提案"。
_DRIFT_KEYS_NUMERIC = ("roi", "spend", "daily_budget")


def _iso_to_utc(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _summary_of(ctx: AgentContext, entity_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """取 connector.current_summary() 中匹配 entity_id 的那一行；缺失时返回 None。"""
    if not entity_id:
        return None
    try:
        rows = ctx.connector.current_summary()
    except Exception:
        return None
    for r in rows or []:
        if str(r.get("campaign_id")) == str(entity_id):
            return {
                "roi": r.get("roi"),
                "spend": r.get("spend"),
                "status": r.get("status"),
                "daily_budget": r.get("daily_budget"),
            }
    return None


def _detect_drift(snapshot: Optional[Dict[str, Any]],
                  current: Optional[Dict[str, Any]],
                  pct: float) -> Optional[str]:
    """返回漂移原因（人类可读）；None 表示可继续执行。快照缺失时视为不漂移。"""
    if not snapshot or not current:
        return None
    snap_status = snapshot.get("status")
    cur_status = current.get("status")
    if snap_status and cur_status and str(snap_status) != str(cur_status):
        return f"status 从 {snap_status} 变为 {cur_status}"
    for k in _DRIFT_KEYS_NUMERIC:
        sv, cv = snapshot.get(k), current.get(k)
        if sv is None or cv is None:
            continue
        try:
            sv_f = float(sv); cv_f = float(cv)
        except (TypeError, ValueError):
            continue
        if abs(sv_f) < 1e-9:
            if abs(cv_f) > 1e-9:
                return f"{k} 从 0 变为 {cv_f:.3g}"
            continue
        rel = abs(cv_f - sv_f) / abs(sv_f)
        if rel > pct:
            return f"{k} 从 {sv_f:.3g} 漂移至 {cv_f:.3g}（{rel*100:.1f}% > 阈值 {pct*100:.0f}%）"
    return None


@dataclass
class Decision:
    action: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    thought: str = ""
    reasoning: str = ""      # 大模型思考过程（推理模型的 reasoning_content）
    final: bool = False
    text: str = ""


class AgentLoop:
    def __init__(self):
        self.registry = get_tool_registry()

    # ============================ 对外入口 ============================ #
    def start(self, session: AgentSession, ctx: AgentContext) -> AgentSession:
        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=f"🎯 目标：{session.goal}", status=AgentStepStatus.DONE.value))
        # 先自动观察一次，给后续决策提供上下文
        obs_tool = self.registry.get("observe_campaigns")
        res = obs_tool.handler({}, ctx)
        session.add_step(AgentStep(
            kind=AgentStepKind.OBSERVATION.value, text=res.observation,
            tool="observe_campaigns", result=res.data, status=AgentStepStatus.DONE.value))
        return self._done(self._run(session, ctx))

    def approve(self, session: AgentSession, step_id: str, approved: bool,
                reason: Optional[str], ctx: AgentContext) -> AgentSession:
        step = next((s for s in session.steps if s.id == step_id), None)
        if not step or step.kind != AgentStepKind.APPROVAL.value:
            raise ValueError("未找到待审批步骤")
        tool = self.registry.get(step.tool)
        if approved:
            # Phase 3.2 —— 审批过期 / 状态漂移校验
            entity_id = (step.params or {}).get("entity_id")
            expired_dt = _iso_to_utc(step.expires_at)
            now_dt = datetime.now(timezone.utc)
            if expired_dt is not None and now_dt > expired_dt:
                step.status = AgentStepStatus.REJECTED.value
                step.text += f"（审批已过期：expires_at={step.expires_at}，超时废弃，将重新规划）"
                session.add_step(AgentStep(
                    kind=AgentStepKind.OBSERVATION.value,
                    text=f"⏱ 审批过期，跳过执行 {tool.name if tool else step.tool}({entity_id})，需要重新观察后再提议。",
                    status=AgentStepStatus.DONE.value))
                session.context.setdefault("rejected", []).append((step.tool, entity_id))
                session.status = "running"
                return self._done(self._run(session, ctx))

            current = _summary_of(ctx, entity_id)
            drift = _detect_drift(step.snapshot, current, settings.agent_approval_drift_pct)
            if drift:
                step.status = AgentStepStatus.REJECTED.value
                step.text += f"（状态漂移：{drift}，废弃旧提案，将重新规划）"
                session.add_step(AgentStep(
                    kind=AgentStepKind.OBSERVATION.value,
                    text=f"⚠ 审批期间实体 {entity_id} 状态漂移：{drift}。跳过旧提案，重新观察后再决策。",
                    status=AgentStepStatus.DONE.value,
                    result={"snapshot": step.snapshot, "current": current}))
                session.context.setdefault("rejected", []).append((step.tool, entity_id))
                session.status = "running"
                return self._done(self._run(session, ctx))

            step.status = AgentStepStatus.APPROVED.value
            if tool and tool.side_effect == "write":
                self._execute_approved_write(session, ctx, step, tool)
            session.status = "running"
            return self._done(self._run(session, ctx))
        else:
            step.status = AgentStepStatus.REJECTED.value
            step.text += f"（已驳回：{reason or '用户拒绝'}）"
            # 记录被驳回的 (工具, 对象)，避免规则引擎反复提议同一动作
            session.context.setdefault("rejected", []).append(
                (step.tool, step.params.get("entity_id")))
            session.status = "running"
            return self._done(self._run(session, ctx))

    def send_message(self, session: AgentSession, text: str,
                     ctx: AgentContext) -> AgentSession:
        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=f"👤 用户：{text}", status=AgentStepStatus.DONE.value))
        session.status = "running"
        return self._done(self._run(session, ctx))

    def redirect_run(self, session: AgentSession, ctx: AgentContext, text: str) -> AgentSession:
        """中途改向：清除中断标志，把新指令注入目标，开启新一轮 ReAct。"""
        session.abort_requested = False
        session.goal = (session.goal or "") + f"\n[用户改向] {text}"
        session.add_step(AgentStep(
            kind=AgentStepKind.OBSERVATION.value,
            text=f"🔀 用户中途改向：{text}",
            status=AgentStepStatus.DONE.value))
        session.status = "running"
        return self._done(self._run(session, ctx))

    def _done(self, session: AgentSession) -> AgentSession:
        """循环结束 / 中断后落库（Phase A1：状态可从 DB 读回），持久化失败不影响主流程。"""
        try:
            get_session_store().persist(session)
        except Exception as e:
            logger.warning("persist session failed: %s", e)
        return session

    def reflect(self, ctx: AgentContext, goal: Optional[str] = None):
        """复盘：基于已沉淀的 Episode 记忆，提取启发式规则（Phase 2 反思层）。"""
        from app.services.agent_runtime.reflection import Reflector
        if ctx.memory is None:
            return None
        return Reflector().reflect(ctx.memory, goal=goal)

    def learn_strategy(self, ctx: AgentContext):
        """策略自演化：把记忆编译成可调用的策略参数（Phase 3 策略层）。"""
        if ctx.strategy is None:
            return None
        return ctx.strategy.learn_from_memory(ctx.memory)

    # ============================ 主循环 ============================ #
    def _run(self, session: AgentSession, ctx: AgentContext) -> AgentSession:
        max_steps = settings.agent_max_steps
        while session.status == "running":
            # —— 用户中断检查（停止 / 中途改向）——
            if session.abort_requested:
                if not session.pending_redirect:
                    self._interrupted(session, ctx)
                break

            acted = [s for s in session.steps
                     if s.kind in (AgentStepKind.ACTION.value, AgentStepKind.OBSERVATION.value,
                                   AgentStepKind.APPROVAL.value)]
            if len(acted) >= max_steps:
                session.add_step(AgentStep(
                    kind=AgentStepKind.FINAL.value,
                    text=_final_summary(session, ctx) + "\n（已达最大步数，请继续下达指令）",
                    status=AgentStepStatus.DONE.value))
                session.status = "done"
                break

            decision = self._decide(session, ctx)
            # 决策刚产生即被中断：不执行、不定稿原结论，直接停机（除非是要改向）
            if session.abort_requested:
                if not session.pending_redirect:
                    self._interrupted(session, ctx)
                break
            if decision.final:
                session.add_step(AgentStep(
                    kind=AgentStepKind.FINAL.value, text=decision.text,
                    status=AgentStepStatus.DONE.value))
                session.status = "done"
                break

            self._dispatch(session, ctx, decision)
            if session.status == "awaiting_approval":
                break
        return session

    def _interrupted(self, session: AgentSession, ctx: AgentContext):
        """用户请求中断：保留已完成步骤，输出中断终态。仅当无 pending_redirect 时调用。"""
        session.add_step(AgentStep(
            kind=AgentStepKind.OBSERVATION.value,
            text="⏹ 用户请求中断，已停止当前循环。以上为已完成的步骤；如需我继续，请说明新的方向。",
            status=AgentStepStatus.DONE.value))
        session.add_step(AgentStep(
            kind=AgentStepKind.FINAL.value,
            text="已根据您的指示中断。",
            status=AgentStepStatus.DONE.value))
        session.status = "done"

    def _execute_approved_write(self, session: AgentSession, ctx: AgentContext,
                                 step: AgentStep, tool) -> None:
        """审批通过后的写动作：走 dispatcher（幂等 + 状态机 + 回读验证）。

        - `tool.handler` 仍然承担媒体调用 + 审计（IntentExecution/ActionLog）——
          dispatcher 把它包成 media_call，避免破坏既有审计链。
        - AgentActionDB 通过 `mint_or_get` 幂等生成，重复审批不会二次写媒体。
        - 回读通过 `ctx.connector.read_state` 完成，命中 → verified，否则 → unknown。
        """
        outcome = self._dispatch_via_action_store(
            session, ctx, tool=tool, params=step.params,
            risk_level=step.risk_level or tool.risk_level,
            step_id=step.id, snapshot=step.snapshot,
            predicted_impact=step.predicted_impact,
        )
        session.add_step(AgentStep(
            kind=AgentStepKind.ACTION.value, text=outcome["text"],
            tool=tool.name, params=step.params, risk_level=step.risk_level,
            status=outcome["status"], result=outcome["data"]))

    def _execute_l0_write(self, session: AgentSession, ctx: AgentContext,
                          tool, params: Dict[str, Any]) -> None:
        """L0 写动作自动执行路径：同样落进 AgentActionDB 状态机。"""
        outcome = self._dispatch_via_action_store(
            session, ctx, tool=tool, params=params,
            risk_level="L0", step_id=None, snapshot=None,
            predicted_impact=self._predict(ctx, tool.name, params),
        )
        session.add_step(AgentStep(
            kind=AgentStepKind.ACTION.value, text=outcome["text"], tool=tool.name,
            params=params, risk_level="L0",
            status=outcome["status"], result=outcome["data"]))

    def _dispatch_via_action_store(self, session: AgentSession, ctx: AgentContext,
                                    *, tool, params: Dict[str, Any], risk_level: str,
                                    step_id: Optional[str],
                                    snapshot: Optional[Dict[str, Any]],
                                    predicted_impact: Optional[Dict[str, Any]]
                                    ) -> Dict[str, Any]:
        """把"审批通过/L0 自动"的写动作交给 Dispatcher 走状态机。

        无 DB（demo）或缺失 action mapping 时回退到旧路径：直接 tool.handler，
        便于不依赖数据库的脚本仍然可跑。
        """
        from app.services.agent_runtime.action_store import ActionRequest
        from app.services.agent_runtime.dispatcher import get_dispatcher
        from app.services.agent_runtime.tools import TOOL_TO_ACTION

        # 无 DB 或工具不在动作映射：兜底走旧的直接执行（demo 场景）
        if ctx.db is None or tool.name not in TOOL_TO_ACTION:
            res = tool.handler(params, ctx)
            return {"text": res.observation,
                    "data": res.data,
                    "status": AgentStepStatus.EXECUTED.value}

        action_name, build_ap = TOOL_TO_ACTION[tool.name]
        action_params = build_ap(params)
        req = ActionRequest(
            session_id=str(session.id),
            step_id=str(step_id or "auto"),
            app_id=ctx.app_id,
            user_id=getattr(ctx.user, "id", None) if ctx.user else None,
            tool=tool.name,
            action=action_name,
            entity_id=params.get("entity_id"),
            platform=getattr(ctx.connector, "platform", None),
            account_id=getattr(ctx.connector, "account_id", None) or None,
            execution_mode=getattr(ctx.connector, "execution_mode", None),
            risk_level=risk_level,
            request={**action_params, "entity_id": params.get("entity_id")},
            pre_state=snapshot,
            predicted_impact=predicted_impact,
        )

        # media_call = tool.handler(...)：既完成媒体调用又完成 IntentExecution/ActionLog 审计
        captured: Dict[str, Any] = {}

        def media_call():
            res = tool.handler(params, ctx)
            captured["result"] = res
            data = res.data or {}
            provider = data.get("result") if isinstance(data.get("result"), dict) else data
            return {"success": bool(res.ok),
                    "provider": provider,
                    "observation": res.observation}

        read_state = getattr(ctx.connector, "read_state", None)
        try:
            outcome = get_dispatcher().dispatch_and_verify(
                ctx.db, req, media_call=media_call, read_state=read_state)
            try:
                ctx.db.commit()
            except Exception as e:
                logger.warning("commit after dispatch failed: %s", e)
                try:
                    ctx.db.rollback()
                except Exception:
                    pass
        except Exception as e:
            logger.exception("dispatch_via_action_store raised, falling back to direct handler")
            res = tool.handler(params, ctx)
            return {"text": f"{res.observation}（dispatcher 异常回退：{e}）",
                    "data": res.data,
                    "status": AgentStepStatus.EXECUTED.value}

        # dispatcher 状态映射到 AgentStepStatus
        state_status = {
            "verified": AgentStepStatus.EXECUTED.value,
            "failed": AgentStepStatus.EXECUTED.value,  # 已进入终态，仍算已执行
            "unknown": AgentStepStatus.EXECUTED.value,
        }.get(outcome.state, AgentStepStatus.EXECUTED.value)

        res = captured.get("result")
        if res is not None:
            observation = f"{res.observation}｜派发状态：{outcome.state}（{outcome.observation}）"
            data = {**(res.data or {}), "dispatch": {
                "state": outcome.state,
                "action_id": outcome.action.id,
                "observation": outcome.observation,
            }}
        else:
            observation = f"派发状态：{outcome.state}（{outcome.observation}）"
            data = {"dispatch": {
                "state": outcome.state,
                "action_id": outcome.action.id,
                "observation": outcome.observation,
            }}
        return {"text": observation, "data": data, "status": state_status}

    def _dispatch(self, session: AgentSession, ctx: AgentContext, decision: Decision):
        tool = self.registry.get(decision.action)
        if tool is None:
            session.add_step(AgentStep(
                kind=AgentStepKind.THOUGHT.value,
                text=f"[未知工具 {decision.action}]，终止本轮", status=AgentStepStatus.DONE.value))
            session.add_step(AgentStep(
                kind=AgentStepKind.FINAL.value,
                text="工具不可用，请调整目标。", status=AgentStepStatus.DONE.value))
            session.status = "done"
            return

        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=decision.thought or f"计划调用 {tool.name}",
            status=AgentStepStatus.DONE.value))

        if tool.side_effect == "read":
            res = tool.handler(decision.params, ctx)
            session.add_step(AgentStep(
                kind=AgentStepKind.OBSERVATION.value, text=res.observation,
                tool=tool.name, result=res.data, status=AgentStepStatus.DONE.value))
            return

        # 写工具
        if tool.risk_level == "L0":
            self._execute_l0_write(session, ctx, tool, decision.params)
            return

        # L1/L2/L3 → 提议，转人在环
        pred = self._predict(ctx, tool.name, decision.params)
        provenance = {
            "platform": getattr(ctx.connector, "platform", None),
            "execution_mode": getattr(ctx.connector, "execution_mode", None),
            "account_id": getattr(ctx.connector, "account_id", None) or None,
        }
        # Phase 3.2：冻结实体快照 + 审批过期时间
        snapshot = _summary_of(ctx, decision.params.get("entity_id"))
        expires_at = (datetime.now(timezone.utc)
                      + timedelta(seconds=settings.agent_approval_ttl_seconds)).isoformat()
        session.add_step(AgentStep(
            kind=AgentStepKind.APPROVAL.value,
            text=f"提议{tool.name}：{_propose_text(tool, decision.params)}",
            tool=tool.name, params=decision.params, risk_level=tool.risk_level,
            predicted_impact=pred, status=AgentStepStatus.PROPOSED.value,
            expires_at=expires_at, snapshot=snapshot,
            result={"provenance": provenance}))
        session.status = "awaiting_approval"

    # ============================ 决策 ============================ #
    def _decide(self, session: AgentSession, ctx: AgentContext) -> Decision:
        if self._llm_available():
            try:
                d = asyncio.run(self._llm_decide(session, ctx))
                if d is not None:
                    return d
            except Exception:
                pass
        return self._rule_based_decide(session, ctx)

    def _llm_available(self) -> bool:
        if not settings.agent_use_llm_planning:
            return False
        try:
            from app.services.llm import is_llm_available
            return is_llm_available()
        except Exception:
            return False

    async def _llm_decide(self, session: AgentSession, ctx: AgentContext) -> Optional[Decision]:
        from app.services.llm import get_llm_router

        router = get_llm_router()
        if router is None:
            return None

        history = []
        for s in session.steps:
            if s.kind == AgentStepKind.THOUGHT.value:
                history.append(f"[思考] {s.text}")
            elif s.kind == AgentStepKind.OBSERVATION.value:
                history.append(f"[观察] {s.text}")
            elif s.kind == AgentStepKind.ACTION.value:
                history.append(f"[已执行] {s.text}")

        sys_prompt = (
            "你是一个海外 UA 投放智能体（ad agent）。给定目标，请按 ReAct 风格逐步决策。\n"
            "可用工具：\n" + self.registry.system_prompt_snippet() + "\n\n"
            "风险分级：L0 自动执行；L1/L2 必须走人在环审批——你只需'提议'，不要自行判定审批结果。\n"
            "每一步只输出一个 JSON（不要多余文字）：\n"
            '  {"thought":"..","action":"工具名","params":{...}}\n'
            '  {"thought":"..","final_answer":"结论文本"}\n\n'
            "【外部数据检索（重要）】\n"
            "当问题涉及**行业基线 / 竞品 CPI / CPA / ROAS / 市场调研 / benchmark / 市场角度**时，"
            "你必须**第一步就调用 `market_research`** 获取外部视角，**禁止只依赖平台内部账户数据作答**。\n"
            "示例：用户问\"ai视频剪辑工具 meta us cpi baseline\" → 先 "
            'market_research(query="ai video editing app CPI benchmark US Meta")，'
            "再结合返回的行业标准给出判断。\n"
            "若需要了解账户现状，调用 observe_campaigns。"
        )
        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.append({"role": "user", "content": "已发生：\n" + "\n".join(history)})
        messages.append({"role": "user", "content": f"目标：{session.goal}\n请决定下一步。"})

        # 先建一个"思考中"占位步骤，让前端立即看到 Agent 进入推理；随后流式填充思考过程
        rstep = session.add_step(AgentStep(
            kind=AgentStepKind.REASONING.value,
            text="🤔 正在调用大模型进行推理…",
            status=AgentStepStatus.THINKING.value))

        try:
            result = await router.chat_completion(
                "campaign.optimize_batch", messages, data_sensitivity="low", stream=True)

            reasoning_buf: List[str] = []
            content_buf: List[str] = []
            is_stream = hasattr(result, "__aiter__")
            if is_stream:
                try:
                    async for chunk in result:
                        ctype = chunk.get("type")
                        if ctype == "reasoning":
                            reasoning_buf.append(chunk.get("text", ""))
                            rstep.text = "🤔 思考中…\n\n" + "".join(reasoning_buf)
                        elif ctype == "content":
                            content_buf.append(chunk.get("text", ""))
                        # 流式细粒度中断：用户点"停止"时，下一个 token 即可退出当前推理
                        if session.abort_requested:
                            rstep.text = "🤔 思考中…（已被用户中断）\n\n" + "".join(reasoning_buf)
                            rstep.status = AgentStepStatus.DONE.value
                            return Decision(final=True, text="（推理已被您中断，等待下一步指令）")
                finally:
                    if hasattr(result, "aclose"):
                        try:
                            await result.aclose()
                        except Exception:
                            pass
                rstep.text = "".join(reasoning_buf) or "（模型未返回显式思考过程）"
                rstep.status = AgentStepStatus.DONE.value
                content = "".join(content_buf)
            else:
                if result.get("fallback_mode") or not result.get("content"):
                    # 无可用 LLM：撤销思考占位步骤，退回规则引擎
                    if session.steps and session.steps[-1] is rstep:
                        session.steps.pop()
                    return None
                reasoning_buf.append(result.get("reasoning") or "")
                rstep.text = result.get("reasoning") or "（模型未返回显式思考过程）"
                rstep.status = AgentStepStatus.DONE.value
                content = result.get("content") or ""

            js = _extract_json(content)
            if not js:
                rstep.text = (rstep.text or "") + "\n\n（模型未返回可解析的 JSON 决策，已退回规则引擎）"
                return None
            if "final_answer" in js:
                return Decision(final=True, text=js["final_answer"], reasoning="".join(reasoning_buf))
            if "action" in js:
                return Decision(action=js.get("action"), params=js.get("params", {}) or {},
                                 thought=js.get("thought", ""), reasoning="".join(reasoning_buf))
            return None
        except Exception as e:
            # 推理调用异常：定稿思考步骤，退回规则引擎
            rstep.text = f"🤔 思考中…\n\n（推理调用异常：{e}）"
            rstep.status = AgentStepStatus.DONE.value
            return None

    # ============================ 规则引擎兜底 ============================ #
    def _rule_based_decide(self, session: AgentSession, ctx: AgentContext) -> Decision:
        goal = session.goal.lower()
        summary = ctx.connector.current_summary()
        done = session.context.setdefault("done", [])
        rejected = session.context.get("rejected", [])
        active = [s for s in summary if s["status"] == "ACTIVE"]

        # 1) 暂停低 ROI
        if any(k in goal for k in ("暂停", "pause", "停掉", "下线", "关掉")) and "lowroi_pause" not in done:
            # Phase 3：学到的暂停阈值优先，回退硬编码默认
            if ctx.strategy is not None and ctx.strategy.has_learned("pause_roi_threshold"):
                threshold = ctx.strategy.advise("pause_roi_threshold", 1.0)
            else:
                threshold = _extract_roi_threshold(goal) or 1.0
            country = _extract_country(goal)
            targets = [s for s in summary if s.get("roi") is not None and s["roi"] < threshold
                       and s["status"] == "ACTIVE"
                       and (not country or s["country"] == country)
                       and ("pause_campaign", s["campaign_id"]) not in rejected]
            if targets:
                t = targets[0]
                remain = [x for x in targets if x["campaign_id"] != t["campaign_id"]]
                if not remain:
                    done.append("lowroi_pause")
                note = f"（另有 {len(remain)} 个待处置）" if remain else ""
                return Decision(
                    action="pause_campaign", params={"entity_id": t["campaign_id"]},
                    thought=f"目标含'暂停低ROI'。{t['campaign_id']} ROI={t['roi']:.2f}<{threshold}，"
                            f"提议暂停止损{note}")
            done.append("lowroi_pause")

        # 2) 给高 ROI 加预算
        if any(k in goal for k in ("加预算", "预算", "budget", "增加预算", "提量", "放量", "加量")) and "highroi_budget" not in done:
            if active and any(k in goal for k in ("高", "roi", "top", "提", "优", "最好")):
                top = max(active, key=lambda s: s["roi"])
                if ("adjust_budget", top["campaign_id"]) not in rejected:
                    inc = _extract_pct(goal) or 20
                    # 学习：Phase 3 学到的策略优先，回退 Phase 2 记忆收敛，再回退硬编码
                    learned = False
                    learn_src = ""
                    if ctx.strategy is not None and ctx.strategy.has_learned("budget_increase_cap"):
                        cap = ctx.strategy.advise("budget_increase_cap", inc)
                        learn_src = "策略"
                    elif ctx.memory is not None:
                        cap = ctx.memory.suggest_budget_increase_cap(default_cap=inc)
                        learn_src = "记忆" if cap < inc else ""
                    else:
                        cap = inc
                    if cap < inc:
                        inc, learned = cap, True
                    camp = getattr(ctx.connector, "engine", None)
                    cur_b = None
                    if camp is not None:
                        c = camp.campaigns.get(top["campaign_id"])
                        cur_b = c.daily_budget if c else None
                    if cur_b:
                        new_b = round(cur_b * (1 + inc / 100), 2)
                        done.append("highroi_budget")
                        learn_note = (f"（{learn_src}收敛：历史加预算边际递减，增幅已收敛至 +%.0f%%）" % inc) if learned else ""
                        return Decision(
                            action="adjust_budget",
                            params={"entity_id": top["campaign_id"], "daily_budget": new_b, "_pct": inc},
                            thought=f"目标含'给高ROI加预算'。{top['campaign_id']} ROI 最高({top['roi']:.2f})，"
                                    f"提议日预算 +{inc}% → {new_b:.0f}{learn_note}")
            done.append("highroi_budget")

        # 3) 换素材
        if any(k in goal for k in ("换素材", "creative", "素材", "疲劳", "下滑", "衰退")) and "rotate_creative" not in done:
            worst = min(active, key=lambda s: s["roi"]) if active else None
            if worst and ("rotate_creative", worst["campaign_id"]) not in rejected:
                done.append("rotate_creative")
                return Decision(
                    action="rotate_creative", params={"entity_id": worst["campaign_id"]},
                    thought=f"目标含'换素材'。{worst['campaign_id']} ROI 最低({worst['roi']:.2f})、素材最疲劳，"
                            f"提议轮换（L0 自动执行）")
            done.append("rotate_creative")

        # 4) 分析 / 报告
        if any(k in goal for k in ("报告", "report", "分析", "诊断", "看看", "查一下", "状态")) and "report" not in done:
            done.append("report")
            return Decision(action="generate_report", params={},
                            thought="目标为分析/报告，调用 generate_report")

        return Decision(final=True, text=_final_summary(session, ctx))

    # ============================ 预测影响 ============================ #
    def _predict(self, ctx: AgentContext, tool_name: str, params: Dict) -> Optional[Dict]:
        if tool_name not in TOOL_TO_ACTION or "entity_id" not in params:
            return None
        action, build = TOOL_TO_ACTION[tool_name]
        ap = build(params)
        try:
            eff = ctx.connector.simulate_impact(action, params["entity_id"], ap, horizon=3)
        except Exception:
            return None
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        return {
            "action": action,
            "entity_id": params["entity_id"],
            "delta_roi_first": eff.delta_roi[0] if eff.delta_roi else 0,
            "delta_roi_avg7": round(avg(eff.delta_roi), 4),
            "delta_spend_first": eff.delta_spend[0] if eff.delta_spend else 0,
        }


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _propose_text(tool, params: Dict) -> str:
    eid = params.get("entity_id", "?")
    if tool.name == "pause_campaign":
        return f"暂停 {eid}（止损，L1 需确认）"
    if tool.name == "resume_campaign":
        return f"恢复 {eid}（L1 需确认）"
    if tool.name == "adjust_budget":
        return f"调整 {eid} 日预算 → {float(params.get('daily_budget', 0)):.0f}（L1 需确认）"
    if tool.name == "adjust_bid":
        return f"调整 {eid} 出价 → {float(params.get('bid_amount', 0)):.2f}x（L2 需确认）"
    return f"{tool.name}({params})"


def _extract_roi_threshold(goal: str) -> Optional[float]:
    m = re.search(r'roi\s*(低于|小于|<|低)\s*([0-9.]+)', goal)
    if not m:
        m = re.search(r'([0-9.]+)\s*以下', goal)
    if m:
        try:
            return float(m.group(2) if m.group(1) in ("低于", "小于", "<", "低") else m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _extract_pct(goal: str) -> Optional[float]:
    m = re.search(r'([0-9]+)\s*%', goal)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    m = re.search(r'增加\s*([0-9.]+)', goal)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    return None


def _extract_country(goal: str) -> Optional[str]:
    mapping = {"美国": "US", "美区": "US", "us": "US", "日本": "JP", "jp": "JP",
               "英国": "UK", "uk": "UK", "德国": "DE", "de": "DE",
               "加拿大": "CA", "ca": "CA", "巴西": "BR", "br": "BR"}
    for k, v in mapping.items():
        if k in goal:
            return v
    return None


def _final_summary(session: AgentSession, ctx: AgentContext) -> str:
    summary = ctx.connector.current_summary()
    executed = [s for s in session.steps
                if s.kind == AgentStepKind.ACTION.value and s.status == AgentStepStatus.EXECUTED.value]
    proposed = [s for s in session.steps
                if s.kind == AgentStepKind.APPROVAL.value and s.status == AgentStepStatus.PROPOSED.value]
    lines = ["✅ 已执行动作："]
    lines += [f"  - {s.text}" for s in executed] or ["  （无）"]
    if proposed:
        lines.append("⏳ 待你审批：")
        lines += [f"  - {s.text}" for s in proposed]
    lines.append("📊 当前账户：")
    for s in summary:
        r = s.get("roi")
        roi_s = f"{r:.2f}" if isinstance(r, (int, float)) else "N/A"
        lines.append(f"  {s['campaign_id']:<12}{s['country']:<4}{s['status']:<8}"
                     f"roi={roi_s:<6}spend={s['spend']:.0f}")
    if not summary:
        lines.append("  （无数据）")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[Dict]:
    try:
        s = text.find("{")
        e = text.rfind("}") + 1
        if s >= 0 and e > s:
            return json.loads(text[s:e])
    except Exception:
        return None
    return None
