from pydantic_settings import BaseSettings
from typing import Optional, Dict, Any, List, Literal
from pathlib import Path
import json


class Settings(BaseSettings):
    database_url: str = "sqlite:///./smartua.db"
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    app_name: str = "SmartUA Platform"
    debug: bool = True
    env: str = "development"
    default_timezone: str = "Asia/Shanghai"

    # 兼容旧配置
    llm_api_key: Optional[str] = None
    llm_model: str = "claude-3-5-sonnet-20241022"

    # LLM 多提供商配置
    claude_api_key: Optional[str] = None
    claude_model: str = "claude-3-5-sonnet-20241022"
    claude_base_url: str = "https://api.anthropic.com/v1"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    deepseek_api_key: Optional[str] = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    # 火山引擎方舟（Volcengine Ark，OpenAI 兼容协议，国内网络友好）
    ark_api_key: Optional[str] = None
    ark_model: str = "ep-xxxxxxxx"   # Ark 推理接入点 Endpoint ID（控制台创建后填入）
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    local_model_base_url: str = "http://localhost:8000/v1"
    local_model_name: str = "qwen2.5-72b-instruct"

    # ===== Google Ads 连接器凭证（真实渠道；缺省时自动回退 mock） =====
    # 填入后 SmartUA 即走真实 Google Ads API（需运行环境能安装 google-ads SDK / grpcio）。
    google_developer_token: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_refresh_token: Optional[str] = None
    google_customer_id: Optional[str] = None        # 运营客户 ID（数字，无连字符）
    google_login_customer_id: Optional[str] = None   # MCC 登录客户 ID（可选）

    # 路由策略: best_fit / fastest / least_cost / highest_quality
    llm_routing_strategy: str = "best_fit"

    # 是否启用 LLM 降级（无可用 LLM 时使用规则引擎）
    llm_fallback_enabled: bool = True

    # ===== Agent Loop（Phase 1）配置 =====
    # Phase 1.1：显式声明连接器的执行目标；不再由凭证/SDK 缺失静默切换。
    # - mock：使用因果模拟数据（默认，安全，绝不接触真实媒体资源）
    # - sandbox：使用平台沙盒 API（当前无实现，作为占位）
    # - live：使用真实媒体 API；缺凭证/SDK/权限必须 fail-closed，绝不回退 mock
    agent_execution_mode: Literal["mock", "sandbox", "live"] = "mock"
    # 默认执行平台：默认 mock，配合 execution_mode=live 且指定真实平台使用。
    agent_default_platform: str = "mock"
    # 单轮决策最大步数，防止 ReAct 无限循环
    agent_max_steps: int = 15
    # 是否在 Agent Loop 中使用 LLM 规划（关闭则纯规则引擎兜底）
    agent_use_llm_planning: bool = True
    # 是否启用 Phase 2 记忆/反思闭环（关闭则写动作不再沉淀 Episode）
    agent_reflection_enabled: bool = True
    # Phase 3 策略自演化：策略参数落盘路径（跨进程/跨账户迁移；None=不落盘）
    agent_strategy_path: Optional[str] = str(
        Path(__file__).resolve().parent.parent / "data" / "strategy.json"
    )

    # ===== Phase 4 主动式自治（Proactive Autonomy）配置 =====
    # 是否启动 APScheduler 后台周期巡检（检测异常并分级处置）
    agent_autonomy_enabled: bool = True
    # 巡检间隔（秒）；开发/演示期设短，生产建议 300（5 分钟）起
    agent_autonomy_interval_seconds: int = 120
    # 同 (异常类型, campaign) 重复告警冷却（扫描次数），避免每轮重复提案
    agent_autonomy_cooldown_scans: int = 3
    # 素材疲劳阈值（天）：creative_age 超过则触发轮换建议（L0 自动）
    agent_fatigue_threshold_days: int = 8
    # 主动监控的 app 列表（演示期仅 app_id=1）
    agent_monitor_app_ids: List[int] = [1]

    # ===== Phase 3.2 审批过期与执行前重校验 =====
    # 提案冻结的审批时效（秒）；超时后审批 API 返回 409，Loop 不再执行该动作。
    agent_approval_ttl_seconds: int = 900
    # 状态漂移阈值（相对变化）：审批通过后重新读取实体，若关键指标（roi/spend/daily_budget）
    # 相对提案快照的相对变化超过此比例，或 status 直接变化，则废弃旧动作、重新规划。
    agent_approval_drift_pct: float = 0.20

    # ===== Tool Pipeline 预算护栏（Middleware） =====
    # 写动作 daily_budget 的相对增幅上限：超过则 BudgetGuard 在审批/执行前短路。
    agent_budget_guard_enabled: bool = True
    agent_budget_max_increase_pct: float = 0.50

    # ===== Phase 2.2 SSE 认证 =====
    # SSE stream-ticket 生存期（秒）：短期 + 单次 + 绑定 (user, session)。
    agent_sse_ticket_ttl_seconds: int = 60
    # 兼容开关：是否允许旧的 ?token=<长期 JWT> 打开 SSE。默认 False，将长期 JWT
    # 从 URL / 代理日志 / 浏览器历史移除；仅在需要向前兼容旧前端时短期开启。
    agent_sse_allow_legacy_token: bool = False

    class Config:
        env_file = ".env"

    def get_llm_providers_config(self) -> Dict[str, Any]:
        """获取 LLM Providers 配置（供路由引擎使用）"""
        return {
            "providers": {
                "claude": {
                    "provider_type": "claude",
                    "name": "Claude 3.5 Sonnet",
                    "api_key": self.claude_api_key or self.llm_api_key,
                    "base_url": self.claude_base_url,
                    "model": self.claude_model,
                    "capabilities": ["complex_intent", "strategy_analysis", "creative_generation"],
                    "cost_per_1k_tokens": 3.0,
                    "avg_latency_ms": 2000,
                    "priority": 1,
                },
                "gpt4": {
                    "provider_type": "gpt4",
                    "name": "GPT-4o",
                    "api_key": self.openai_api_key,
                    "base_url": self.openai_base_url,
                    "model": self.openai_model,
                    "capabilities": ["fast_response", "creative_generation"],
                    "cost_per_1k_tokens": 2.5,
                    "avg_latency_ms": 1500,
                    "priority": 2,
                },
                "deepseek": {
                    "provider_type": "deepseek",
                    "name": "DeepSeek V3",
                    "api_key": self.deepseek_api_key,
                    "base_url": self.deepseek_base_url,
                    "model": self.deepseek_model,
                    "capabilities": ["code_generation", "fast_response"],
                    "cost_per_1k_tokens": 1.0,
                    "avg_latency_ms": 800,
                    "priority": 3,
                },
                "ark": {
                    "provider_type": "ark",
                    "name": "Volcengine Ark (方舟)",
                    "api_key": self.ark_api_key,
                    "base_url": self.ark_base_url,
                    "model": self.ark_model,
                    "capabilities": ["complex_intent", "strategy_analysis",
                                    "creative_generation", "fast_response"],
                    "cost_per_1k_tokens": 0.8,
                    "avg_latency_ms": 1200,
                    "priority": 1,
                },
                "local": {
                    "provider_type": "local",
                    "name": "Qwen 2.5 72B",
                    "type": "local",
                    "base_url": self.local_model_base_url,
                    "model": self.local_model_name,
                    "api_key": "local",
                    "capabilities": ["sensitive_data", "internal_analysis"],
                    "cost_per_1k_tokens": 0.1,
                    "avg_latency_ms": 5000,
                    "priority": 4,
                },
            },
            "routing_rules": [
                {
                    "intent": "campaign.optimize_batch",
                    "required_capabilities": ["complex_intent", "strategy_analysis"],
                    "preferred_provider": "claude",
                    "fallback_provider": "gpt4",
                },
                {
                    "intent": "creative.rotate",
                    "required_capabilities": ["creative_generation"],
                    "preferred_provider": "ark",
                    "fallback_provider": "gpt4",
                },
                {
                    "intent": "campaign.optimize_batch",
                    "required_capabilities": ["complex_intent", "strategy_analysis"],
                    "preferred_provider": "ark",
                    "fallback_provider": "claude",
                },
                {
                    "intent": "*",
                    "strategy": self.llm_routing_strategy,
                    "fallback_provider": "deepseek",
                },
            ]
        }

    @property
    def google_credentials_dict(self) -> Dict[str, Any]:
        """汇聚 google_* 凭证字段为连接器所需 dict（仅含非 None 项）。

        供 resolve_credentials 在库表无凭证时回退；为空则 GoogleAdsConnector 自动走 mock。
        连接器期望的 key 为 client_id/client_secret/refresh_token/developer_token/
        customer_id/login_customer_id（即去掉 google_ 前缀）。
        """
        creds: Dict[str, Any] = {}
        for key in ("google_developer_token", "google_client_id", "google_client_secret",
                    "google_refresh_token", "google_customer_id", "google_login_customer_id"):
            val = getattr(self, key, None)
            if val:
                creds[key.replace("google_", "")] = val
        return creds


settings = Settings()
