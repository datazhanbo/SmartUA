"""SkillLoader 单测：frontmatter 解析、参数合并、prompt 片段、重载。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.agent_runtime.skills import Skill, SkillStore
from app.services.agent_runtime.skills.loader import reset_skill_store


VALID_SKILL = """---
name: scale_winning
description: 加预算 20%
target_tool: adjust_budget
params:
  _pct: 0.20
when: ROI > 1.5
---

执行流程：

1. 先观察。
2. 再调 adjust_budget。
"""


DISABLED_SKILL = """---
name: disabled_one
enabled: false
target_tool: pause_campaign
---
不应被加载。
"""


MALFORMED_YAML = """---
name: bad
params: : :
---
正文。
"""


NO_FRONTMATTER = "没有 frontmatter 的文本"


NO_NAME = """---
description: 缺 name
---
正文。
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_from_string_parses_all_fields():
    s = Skill.from_string(VALID_SKILL, source_path="x.md")
    assert s.name == "scale_winning"
    assert s.description == "加预算 20%"
    assert s.target_tool == "adjust_budget"
    assert s.params == {"_pct": 0.20}
    assert s.when == "ROI > 1.5"
    assert s.enabled is True
    assert "观察" in s.body
    assert s.path == "x.md"


def test_prompt_block_contains_key_sections():
    s = Skill.from_string(VALID_SKILL)
    block = s.prompt_block()
    assert "scale_winning" in block
    assert "adjust_budget" in block
    assert "0.2" in block
    assert "执行流程" in block


def test_missing_frontmatter_raises():
    with pytest.raises(ValueError):
        Skill.from_string(NO_FRONTMATTER)


def test_missing_name_raises():
    with pytest.raises(ValueError):
        Skill.from_string(NO_NAME)


def test_store_reload_skips_disabled_and_malformed(tmp_path):
    _write(tmp_path, "good.md", VALID_SKILL)
    _write(tmp_path, "disabled.md", DISABLED_SKILL)
    _write(tmp_path, "bad.md", MALFORMED_YAML)

    store = SkillStore(str(tmp_path))
    names = {s.name for s in store.all()}
    assert names == {"scale_winning"}


def test_apply_params_caller_wins(tmp_path):
    _write(tmp_path, "s.md", VALID_SKILL)
    store = SkillStore(str(tmp_path))

    merged = store.apply_params("adjust_budget", {"daily_budget": 120.0})
    assert merged["_pct"] == 0.20
    assert merged["daily_budget"] == 120.0

    # caller overrides skill default
    merged2 = store.apply_params("adjust_budget", {"_pct": 0.5})
    assert merged2["_pct"] == 0.5


def test_apply_params_no_matching_skill_is_passthrough(tmp_path):
    store = SkillStore(str(tmp_path))
    out = store.apply_params("pause_campaign", {"entity_id": "x"})
    assert out == {"entity_id": "x"}


def test_for_tool_filters_by_target(tmp_path):
    _write(tmp_path, "s.md", VALID_SKILL)
    store = SkillStore(str(tmp_path))
    assert store.for_tool("adjust_budget")[0].name == "scale_winning"
    assert store.for_tool("pause_campaign") == []


def test_effective_risk_level_override(tmp_path):
    text = """---
name: risky
target_tool: adjust_budget
risk_level: L2
---
"""
    _write(tmp_path, "r.md", text)
    store = SkillStore(str(tmp_path))
    assert store.effective_risk_level("adjust_budget", "L1") == "L2"
    assert store.effective_risk_level("pause_campaign", "L1") == "L1"


def test_prompt_snippets_empty_when_no_skills(tmp_path):
    store = SkillStore(str(tmp_path))
    assert store.prompt_snippets() == ""


def test_prompt_snippets_includes_header(tmp_path):
    _write(tmp_path, "s.md", VALID_SKILL)
    store = SkillStore(str(tmp_path))
    out = store.prompt_snippets()
    assert "可用 Skill" in out
    assert "scale_winning" in out


def test_singleton_respects_enabled_flag(monkeypatch, tmp_path):
    reset_skill_store(str(tmp_path))
    from app.services.agent_runtime.skills.loader import get_skill_store
    store = get_skill_store()
    assert isinstance(store, SkillStore)
    reset_skill_store(None)
