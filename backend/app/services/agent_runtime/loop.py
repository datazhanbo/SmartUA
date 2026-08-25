"""Agent Loop —— 薄壳 ReAct 编排（v4，P0 升级后）。

职责：
- ReAct while 主循环（think → select tool → (execute | propose) → observe）
- LLM 决策（_llm_decide）+ 规则引擎兜底（planner.rule_based_decide）
- 把每次工具调用交给 Tool Pipeline（middleware chain）
- 审批入口（approve）薄壳：过期/漂移校验委托给 pipeline.approval

工具管线横切关注点（预算护栏、未来的 PII/MCP 路由等）走 `agent_runtime/pipeline/`，
新增 middleware 不需要改本文件。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.agent_runtime.pipeline import (
    ToolCall, ToolCallResult, build_chain,
    check_approval, execute_tool_call, freeze_snapshot,
    is_read_tool, is_l0_auto, needs_approval, provenance_of,
)
from app.services.agent_runtime.planner import (
    rule_based_decide, final_summary as _final_summary,
    extract_json as _extract_json,
    propose_text as _planner_propose_text,
)
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, get_session_store,
)
from app.services.agent_runtime.tools import (
    AgentContext, TOOL_TO_ACTION, get_tool_registry,
)

# 向后兼容 re-export：api/v1/agent.py 和测试直接 import 这些符号，不能断。
from app.services.agent_runtime.pipeline.approval import (  # noqa: F401
    _summary_of, _detect_drift, _DRIFT_KEYS_NUMERIC, _iso_to_utc,
)


def _propose_text(tool, params: Dict) -> str:
    return _planner_propose_text(tool, params)


logger = logging.getLogger(__name__)


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
        self.chain = build_chain()

    # ============================ 对外入口 ============================ #
    def start(self, session: AgentSession, ctx: AgentContext) -> AgentSession:
        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=f"🎯 目标：{session.goal}", status=AgentStepStatus.DONE.value))
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

        if not approved:
            step.status = AgentStepStatus.REJECTED.value
            step.text += f"（已驳回：{reason or '用户拒绝'}）"
            session.context.setdefault("rejected", []).append(
                (step.tool, (step.params or {}).get("entity_id")))
            session.status = "running"
            return self._done(self._run(session, ctx))

        ok, why, current = check_approval(step, ctx)
        if not ok:
            step.status = AgentStepStatus.REJECTED.value
            if why == "expired":
                step.text += f"（审批已过期：expires_at={step.expires_at}，超时废弃，将重新规划）"
                obs = (f"⏱ 审批过期，跳过执行 {tool.name if tool else step.tool}"
                       f"({(step.params or {}).get('entity_id')})，需要重新观察后再提议。")
            else:
                drift_msg = why.split("drift:", 1)[1] if why.startswith("drift:") else why
                step.text += f"（状态漂移：{drift_msg}，废弃旧提案，将重新规划）"
                obs = (f"⚠ 审批期间实体状态漂移：{drift_msg}。跳过旧提案，重新观察后再决策。")
            session.add_step(AgentStep(
                kind=AgentStepKind.OBSERVATION.value, text=obs,
                status=AgentStepStatus.DONE.value,
                result={"snapshot": step.snapshot, "current": current}))
            session.context.setdefault("rejected", []).append(
                (step.tool, (step.params or {}).get("entity_id")))
            session.status = "running"
            return self._done(self._run(session, ctx))

        step.status = AgentStepStatus.APPROVED.value
        if tool and tool.side_effect == "write":
            call = self._build_call(tool, step.params, ctx, trigger="approved",
                                    step_id=step.id, snapshot=step.snapshot,
                                    predicted_impact=step.predicted_impact)
            self._execute_through_chain(call, session)
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
        session.abort_requested = False
        session.goal = (session.goal or "") + f"\n[用户改向] {text}"
        session.add_step(AgentStep(
            kind=AgentStepKind.OBSERVATION.value,
            text=f"🔀 用户中途改向：{text}",
            status=AgentStepStatus.DONE.value))
        session.status = "running"
        return self._done(self._run(session, ctx))

    def reflect(self, ctx: AgentContext, goal: Optional[str] = None):
        from app.services.agent_runtime.reflection import Reflector
        if ctx.memory is None:
            return None
        return Reflector().reflect(ctx.memory, goal=goal)

    def learn_strategy(self, ctx: AgentContext):
        if ctx.strategy is None:
            return None
        return ctx.strategy.learn_from_memory(ctx.memory)

    def _done(self, session: AgentSession) -> AgentSession:
        try:
            get_session_store().persist(session)
        except Exception as e:
            logger.warning("persist session failed: %s", e)
        return session

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

    # ============================ 工具调度（pipeline 驱动） ============================ #
    def _build_call(self, tool, params, ctx, *, trigger: str,
                    step_id=None, snapshot=None, predicted_impact=None) -> ToolCall:
        return ToolCall(
            name=tool.name, params=params, tool=tool, ctx=ctx,
            risk_level=tool.risk_level, side_effect=tool.side_effect,
            trigger=trigger, step_id=step_id, snapshot=snapshot,
            predicted_impact=predicted_impact)

    def _execute_through_chain(self, call: ToolCall, session: AgentSession) -> Optional[ToolCallResult]:
        """走 middleware chain 执行 ToolCall，结果落 AgentStep。

        返回 ToolCallResult；被 middleware 拒绝时返回 denied 结果，调用方决定是否继续。
        """
        def executor(c: ToolCall) -> ToolCallResult:
            step = execute_tool_call(c, session)
            session.steps.append(step)
            return ToolCallResult(
                ok=step.status != "failed",
                observation=step.text or "",
                data=step.result or {},
                status="executed")

        result = self.chain.execute(call, executor)
        if result.status == "denied":
            session.add_step(AgentStep(
                kind=AgentStepKind.OBSERVATION.value,
                text=result.observation, tool=call.name, result=result.data,
                status=AgentStepStatus.DONE.value))
        return result

    def _dispatch(self, session: AgentSession, ctx: AgentContext, decision: Decision) -> None:
        tool = self.registry.get(decision.action)
        if tool is None:
            session.add_step(AgentStep(
                kind=AgentStepKind.THOUGHT.value,
                text=f"[未知工具 {decision.action}]，终止本轮",
                status=AgentStepStatus.DONE.value))
            session.add_step(AgentStep(
                kind=AgentStepKind.FINAL.value,
                text="工具不可用，请调整目标。", status=AgentStepStatus.DONE.value))
            session.status = "done"
            return

        session.add_step(AgentStep(
            kind=AgentStepKind.THOUGHT.value,
            text=decision.thought or f"计划调用 {tool.name}",
            status=AgentStepStatus.DONE.value))

        # read 工具：直接执行
        if is_read_tool(tool):
            call = self._build_call(tool, decision.params, ctx, trigger="read")
            self._execute_through_chain(call, session)
            return

        # L0 自动写：走 middleware chain（含 BudgetGuard）
        if is_l0_auto(tool):
            call = self._build_call(
                tool, decision.params, ctx, trigger="l0",
                predicted_impact=self._predict(ctx, tool.name, decision.params))
            self._execute_through_chain(call, session)
            return

        # L1/L2/L3 → 先过 BudgetGuard，通过则冻结快照转人在环
        if needs_approval(tool):
            call = self._build_call(tool, decision.params, ctx, trigger="proposed")
            for mw in self.chain:
                short = mw.before(call)
                if short is not None and short.status == "denied":
                    session.add_step(AgentStep(
                        kind=AgentStepKind.OBSERVATION.value,
                        text=short.observation, tool=tool.name, result=short.data,
                        status=AgentStepStatus.DONE.value))
                    return

            pred = self._predict(ctx, tool.name, decision.params)
            fz = freeze_snapshot(ctx, decision.params)
            session.add_step(AgentStep(
                kind=AgentStepKind.APPROVAL.value,
                text=f"提议{tool.name}：{_propose_text(tool, decision.params)}",
                tool=tool.name, params=decision.params, risk_level=tool.risk_level,
                predicted_impact=pred, status=AgentStepStatus.PROPOSED.value,
                expires_at=fz["expires_at"], snapshot=fz["snapshot"],
                result={"provenance": provenance_of(ctx)}))
            session.status = "awaiting_approval"
            return

        # 兜底：未知 risk_level 当作只读处理
        res = tool.handler(decision.params, ctx)
        session.add_step(AgentStep(
            kind=AgentStepKind.OBSERVATION.value, text=res.observation,
            tool=tool.name, result=res.data, status=AgentStepStatus.DONE.value))

    # ============================ 决策 ============================ #
    def _decide(self, session: AgentSession, ctx: AgentContext) -> Decision:
        if self._llm_available():
            try:
                d = asyncio.run(self._llm_decide(session, ctx))
                if d is not None:
                    return d
            except Exception:
                pass
        return rule_based_decide(session, ctx)

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
