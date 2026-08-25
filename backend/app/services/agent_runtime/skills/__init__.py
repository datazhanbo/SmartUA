"""Skill 包：`.md` 文件作为已有工具的参数化配置 + 提示词层。

Skill **不注册新工具**——工程师写底层 tool（base bundle），优化师写 `.md` skill
（patch / 配置层），指定默认参数和执行流程，指导 LLM 调用已有工具。
"""
from app.services.agent_runtime.skills.loader import (
    Skill, SkillStore, get_skill_store,
)

__all__ = ["Skill", "SkillStore", "get_skill_store"]
