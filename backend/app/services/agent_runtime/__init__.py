"""Agent Loop 运行时包（Phase 1：规划 + ReAct + 多轮 + 人在环）。

- session.py  : 多轮会话状态 + 内存仓库
- tools.py    : Tool/Skill Registry（桥接平台工具与 Agent，带 L0-L3 风险元数据）
- loop.py     : ReAct 编排（规则引擎兜底 + LLM 规划 + 人在环审批）

平台做"身体+护栏"，Agent Loop 做"大脑"。
"""
from app.services.agent_runtime.session import (
    AgentSession, AgentStep, AgentStepKind, AgentStepStatus, AgentSessionStore,
    get_session_store,
)
from app.services.agent_runtime.tools import (
    AgentContext, Tool, ToolResult, ToolRegistry, get_tool_registry, TOOL_TO_ACTION,
)
from app.services.agent_runtime.loop import AgentLoop, Decision
from app.services.agent_runtime.memory import (
    Episode, EpisodicMemory, get_memory,
)
from app.services.agent_runtime.reflection import Reflector, ReflectionResult
from app.services.agent_runtime.strategy import (
    StrategyStore, StrategyRule, StrategyLearnResult, get_strategy,
)
from app.services.agent_runtime.autonomy import (
    AnomalyType, Anomaly, AutonomyAlert, AnomalyDetector,
    AutonomyEngine, AutonomyStore,
    get_autonomy_store, start_scheduler, stop_scheduler, update_alert_for_session,
)

__all__ = [
    "AgentSession", "AgentStep", "AgentStepKind", "AgentStepStatus",
    "AgentSessionStore", "get_session_store",
    "AgentContext", "Tool", "ToolResult", "ToolRegistry", "get_tool_registry",
    "TOOL_TO_ACTION", "AgentLoop", "Decision",
    "Episode", "EpisodicMemory", "get_memory",
    "Reflector", "ReflectionResult",
    "StrategyStore", "StrategyRule", "StrategyLearnResult", "get_strategy",
    "AnomalyType", "Anomaly", "AutonomyAlert", "AnomalyDetector",
    "AutonomyEngine", "AutonomyStore",
    "get_autonomy_store", "start_scheduler", "stop_scheduler", "update_alert_for_session",
]
