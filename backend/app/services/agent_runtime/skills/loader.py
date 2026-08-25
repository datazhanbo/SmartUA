"""SkillLoader —— 扫描 `.md` skill 文件，解析 YAML frontmatter。

Skill 的边界（见 docs/SKILL_SYSTEM.md）：
- Skill **不注册新工具**；它给已有工具提供参数默认值 + 一段指导 LLM 的流程文本。
- frontmatter 字段：
    name:         唯一标识
    description:  一句话说明（进入 system prompt）
    target_tool:  可选；指定后 apply_params 只对该工具合并默认参数
    params:       dict，合并进该工具调用的默认参数（LLM 显式给的参数优先）
    when:         可选，触发条件的自然语言描述（仅供 LLM 参考，不做硬规则）
    risk_level:   可选，覆盖 target_tool 的风险分级（L0/L1/L2/L3）；通常不建议改
    enabled:      默认 true；false 则跳过
- 正文（frontmatter 之后的 Markdown）作为执行流程提示片段，追加进 system prompt。

设计原则：文件系统扫描，无数据库、无热更新 UI；reload() 可在不重启服务时重扫。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


@dataclass
class Skill:
    name: str
    description: str = ""
    target_tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    when: Optional[str] = None
    risk_level: Optional[str] = None
    body: str = ""
    path: Optional[str] = None
    enabled: bool = True

    @classmethod
    def from_file(cls, path: Path) -> "Skill":
        text = path.read_text(encoding="utf-8")
        return cls.from_string(text, source_path=str(path))

    @classmethod
    def from_string(cls, text: str, source_path: Optional[str] = None) -> "Skill":
        m = _FRONTMATTER_RE.match(text)
        if not m:
            raise ValueError(f"skill 缺少 frontmatter: {source_path or '<string>'}")
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"skill frontmatter YAML 解析失败 {source_path}: {e}") from e
        if not isinstance(meta, dict):
            raise ValueError(f"skill frontmatter 必须是 mapping: {source_path}")
        name = meta.get("name")
        if not name:
            raise ValueError(f"skill 缺少 name 字段: {source_path}")
        return cls(
            name=str(name),
            description=str(meta.get("description", "")),
            target_tool=meta.get("target_tool"),
            params=dict(meta.get("params") or {}),
            when=meta.get("when"),
            risk_level=meta.get("risk_level"),
            body=m.group(2).strip(),
            path=source_path,
            enabled=bool(meta.get("enabled", True)),
        )

    def prompt_block(self) -> str:
        """进入 system prompt 的片段。"""
        head = f"### Skill: {self.name}"
        if self.target_tool:
            head += f"（作用于工具 `{self.target_tool}`）"
        lines = [head]
        if self.description:
            lines.append(self.description)
        if self.when:
            lines.append(f"触发条件：{self.when}")
        if self.params:
            lines.append(f"默认参数：{self.params}（用户/模型显式给的参数优先）")
        if self.body:
            lines.append(self.body)
        return "\n".join(lines)


class SkillStore:
    """扫描目录、持有 Skill 集合、提供参数合并与 prompt 片段。"""

    def __init__(self, directory: Optional[str] = None):
        self.directory = Path(directory) if directory else None
        self._skills: Dict[str, Skill] = {}
        if self.directory:
            self.reload()

    def reload(self) -> int:
        """重新扫描目录，返回加载成功的 skill 数。失败的文件记 warning 并跳过。"""
        self._skills.clear()
        if not self.directory or not self.directory.exists():
            return 0
        count = 0
        for path in sorted(self.directory.glob("*.md")):
            try:
                skill = Skill.from_file(path)
            except Exception as e:
                logger.warning("跳过 skill %s：%s", path.name, e)
                continue
            if not skill.enabled:
                continue
            if skill.name in self._skills:
                logger.warning("skill 名重复 %s（%s），后者覆盖", skill.name, path)
            self._skills[skill.name] = skill
            count += 1
        return count

    def all(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def for_tool(self, tool_name: str) -> List[Skill]:
        """返回作用于指定工具的 skill（target_tool 为空的全局 skill 不返回）。"""
        return [s for s in self._skills.values() if s.target_tool == tool_name]

    def apply_params(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """把 skill 的默认参数合并进 params；显式参数优先，不覆盖。"""
        merged: Dict[str, Any] = {}
        for sk in self.for_tool(tool_name):
            merged.update(sk.params)
        merged.update(params or {})
        return merged

    def effective_risk_level(self, tool_name: str, default: str) -> str:
        """若 skill 显式指定 risk_level，则覆盖默认。"""
        for s in self.for_tool(tool_name):
            if s.risk_level:
                return s.risk_level
        return default

    def prompt_snippets(self) -> str:
        """所有启用 skill 的 prompt 片段拼接（进入 system prompt）。无 skill 返回空串。"""
        if not self._skills:
            return ""
        blocks = [s.prompt_block() for s in self._skills.values()]
        return "【可用 Skill（优化师预置流程与默认参数）】\n" + "\n\n".join(blocks)


_store: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    """进程级单例。目录来自 settings.agent_skills_dir；可在测试中 reset。"""
    global _store
    if _store is None:
        from app.config import settings
        directory = settings.agent_skills_dir if settings.agent_skills_enabled else None
        _store = SkillStore(directory)
    return _store


def reset_skill_store(directory: Optional[str] = None) -> SkillStore:
    """测试钩子：重置单例。"""
    global _store
    _store = SkillStore(directory)
    return _store
