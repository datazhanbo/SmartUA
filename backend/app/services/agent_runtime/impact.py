"""Phase 4.1 —— 三类影响（predicted / observed / attributed）的公共 envelope。

**为什么单独一个模块**：三类字段在 `AgentActionDB` / `IntentExecution` / `Episode` /
`memory` / `reflection` / `strategy` 里都要读写；如果只用裸 dict，字段命名会漂。
本模块定义**唯一的形状**和构造器，所有生产者都从这里生成，所有消费者都从这里读。

**三类语义**（严格区分，禁止互相冒充）：

- `predicted`：模型/引擎在动作**发生之前**预测的影响。来源：`simulate_impact()`
  的反事实模拟、LLM 估计等。**没有真实事实作为依据**。
- `observed`：动作**已经生效之后**从媒体侧读到的**账面变化**。来源：Google Ads
  Reports、Meta Insights、TikTok Ads 等。**只反映媒体记录的数字**，不含归因判断。
- `attributed`：把变化归因到「本次动作」的部分。来源：MMP（AppsFlyer / Adjust）
  的归因事件、DiD / matched control 等因果推断结果。**是最接近真实业务效果的层**。

**envelope 字段**（每一层都用同一形状）：

- `metrics`（dict）：`{delta_roi, delta_spend, delta_cpi, ...}` —— 具体指标由三类共享。
- `window`（str）：`"24h" / "7d" / "2h"` 等。predicted 常用 `"24h"` / `"7d"`；observed
  按回采窗口；attributed 按 MMP 窗口。
- `time_zone`（str）：数据基准时区（如 `"UTC"` / `"Asia/Shanghai"`）。
- `currency`（str）：金额币种（`"USD"` 等）。predicted 里当前引擎默认 USD。
- `source`（str）：来源标识 —— `"simulate_impact"` / `"google_ads_report"` /
  `"appsflyer_mmp"` 等，便于审计溯源。
- `freshness`（str | None）：ISO 时间戳，表示数据"截止/生成"时刻。predicted 是动作
  发生前提议时刻；observed / attributed 是回采时刻。
- `completeness`（float | None）：0.0–1.0，表示数据完整性（如 MMP 覆盖率 90%
  即 0.9）。predicted 恒为 1.0（模型输入是完备的），observed / attributed 视回采实际。

**不做的事**：
- 不给缺失字段填 0 —— 缺就是 `None`。这是 Phase 4.1 的核心不变量：**没有回采到就不
  能冒充有效果**。
- 不做单位换算 / 时区归一 —— 由消费者决定；envelope 只忠实记录。
- 不做 predicted vs observed 的差分（那是 Phase 7 反思层的事）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


ImpactKind = str  # "predicted" | "observed" | "attributed"


@dataclass
class ImpactEnvelope:
    """三类影响共享的载荷。"""
    kind: ImpactKind
    metrics: Dict[str, Any] = field(default_factory=dict)
    window: Optional[str] = None
    time_zone: str = "UTC"
    currency: Optional[str] = "USD"
    source: Optional[str] = None
    freshness: Optional[str] = None
    completeness: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "metrics": dict(self.metrics or {}),
            "window": self.window,
            "time_zone": self.time_zone,
            "currency": self.currency,
            "source": self.source,
            "freshness": self.freshness,
            "completeness": self.completeness,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> Optional["ImpactEnvelope"]:
        if not d or not isinstance(d, dict):
            return None
        return cls(
            kind=d.get("kind") or "predicted",
            metrics=dict(d.get("metrics") or {}),
            window=d.get("window"),
            time_zone=d.get("time_zone") or "UTC",
            currency=d.get("currency"),
            source=d.get("source"),
            freshness=d.get("freshness"),
            completeness=d.get("completeness"),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_predicted(metrics: Dict[str, Any], *, window: str = "24h",
                   source: str = "simulate_impact",
                   currency: str = "USD",
                   time_zone: str = "UTC") -> Dict[str, Any]:
    """构造 predicted envelope。freshness 记为"生成此预测的时刻"。"""
    return ImpactEnvelope(
        kind="predicted",
        metrics=metrics or {},
        window=window,
        time_zone=time_zone,
        currency=currency,
        source=source,
        freshness=_now_iso(),
        completeness=1.0,
    ).to_dict()


def make_observed(metrics: Dict[str, Any], *, window: str,
                  source: str,
                  currency: Optional[str] = None,
                  time_zone: str = "UTC",
                  freshness: Optional[str] = None,
                  completeness: Optional[float] = None) -> Dict[str, Any]:
    """构造 observed envelope。缺任何字段就传 None —— 不要用 0 假装有效果。"""
    return ImpactEnvelope(
        kind="observed",
        metrics=metrics or {},
        window=window,
        time_zone=time_zone,
        currency=currency,
        source=source,
        freshness=freshness or _now_iso(),
        completeness=completeness,
    ).to_dict()


def make_attributed(metrics: Dict[str, Any], *, window: str,
                    source: str,
                    currency: Optional[str] = None,
                    time_zone: str = "UTC",
                    freshness: Optional[str] = None,
                    completeness: Optional[float] = None) -> Dict[str, Any]:
    """构造 attributed envelope。来源必须能追溯到 MMP / 归因模型。"""
    return ImpactEnvelope(
        kind="attributed",
        metrics=metrics or {},
        window=window,
        time_zone=time_zone,
        currency=currency,
        source=source,
        freshness=freshness or _now_iso(),
        completeness=completeness,
    ).to_dict()


def metric(envelope: Optional[Dict[str, Any]], key: str,
           default: Optional[float] = None) -> Optional[float]:
    """从 envelope 里安全取一个指标。envelope 缺 / kind 不对 / 键不存在都返回 default。

    **消费方约定**：想取 observed 的时候就传 observed envelope；不要自动 fallback
    到 predicted —— Phase 4.1 明确 predicted 不能替代 observed 参与学习门禁。
    """
    if not envelope or not isinstance(envelope, dict):
        return default
    metrics = envelope.get("metrics") or {}
    val = metrics.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default
