"""Agent Loop 会话状态（多轮对话 / 计划 / 审批）。

设计要点：
- 与"平台做身体+护栏，Agent Loop 做大脑"一致：会话只持有"目标、步骤、待审批项、上下文"，
  真实执行仍走 Connector / 意图引擎（审计、安全分级天然生效）。
- 当前为**进程内内存仓库**（开发期 + demo 友好，与 MockMediaConnector 的单例引擎同源）。
  生产环境需落库 + 接 Episodic Memory（见 Phase 2）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentStepKind(str, Enum):
    REASONING = "reasoning"    # 大模型思考过程（推理模型的 reasoning_content，逐 token 流式）
    THOUGHT = "thought"        # 推理结论（模型在 JSON 中给出的 thought 摘要）
    ACTION = "action"          # 已执行的写动作
    OBSERVATION = "observation"  # 读/观察结果
    APPROVAL = "approval"      # 待人确认的高风险动作
    FINAL = "final"            # 最终结论


class AgentStepStatus(str, Enum):
    PROPOSED = "proposed"      # 等待人确认
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    THINKING = "thinking"      # 大模型正在流式思考中（reasoning 步骤）
    DONE = "done"              # 观察/结论已落定


class AgentStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: str
    text: str
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    risk_level: Optional[str] = None
    predicted_impact: Optional[Dict[str, Any]] = None
    status: str = "done"
    result: Optional[Dict[str, Any]] = None
    created_at: str = Field(default_factory=_now)

    def short(self) -> str:
        tag = {
            AgentStepKind.REASONING.value: "🧠",
            AgentStepKind.THOUGHT.value: "💭",
            AgentStepKind.OBSERVATION.value: "👁",
            AgentStepKind.ACTION.value: "✅",
            AgentStepKind.APPROVAL.value: "⏳",
            AgentStepKind.FINAL.value: "🏁",
        }.get(self.kind, "•")
        meta = ""
        if self.risk_level:
            meta = f" [{self.risk_level}]"
        return f"{tag} {self.text}{meta}"


class AgentSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    app_id: int
    user_id: int
    goal: str
    status: str = "running"   # running / awaiting_approval / done / failed
    steps: List[AgentStep] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)  # 累计观察（如最近一次 summary）
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    abort_requested: bool = False            # 用户请求中断当前循环
    pending_redirect: Optional[str] = None    # 用户中途改向：中断后按此新指令续跑

    def add_step(self, step: AgentStep) -> AgentStep:
        self.steps.append(step)
        self.updated_at = _now()
        return step

    def touch(self):
        self.updated_at = _now()

    def pending_approval(self) -> Optional[AgentStep]:
        for s in self.steps:
            if s.kind == AgentStepKind.APPROVAL.value and s.status == AgentStepStatus.PROPOSED.value:
                return s
        return None

    def plan_view(self) -> List[str]:
        """给前端/用户看的步骤时间线。"""
        return [s.short() for s in self.steps]


class AgentSessionStore:
    """进程内会话仓库（单例）。开发期足够；生产需替换为 DB-backed。"""

    def __init__(self):
        self._sessions: Dict[str, AgentSession] = {}

    def create(self, app_id: int, user_id: int, goal: str) -> AgentSession:
        s = AgentSession(app_id=app_id, user_id=user_id, goal=goal)
        self._sessions[s.id] = s
        return s

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)

    def list(self, app_id: int) -> List[AgentSession]:
        return [s for s in self._sessions.values() if s.app_id == app_id]

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None


# 全局单例（与 MockMediaConnector 的引擎单例机制一致）
_session_store: Optional[AgentSessionStore] = None


def get_session_store() -> AgentSessionStore:
    global _session_store
    if _session_store is None:
        _session_store = AgentSessionStore()
    return _session_store
