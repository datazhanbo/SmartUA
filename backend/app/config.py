from pydantic_settings import BaseSettings
from typing import Optional, Dict, Any
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

    local_model_base_url: str = "http://localhost:8000/v1"
    local_model_name: str = "qwen2.5-72b-instruct"

    # 路由策略: best_fit / fastest / least_cost / highest_quality
    llm_routing_strategy: str = "best_fit"

    # 是否启用 LLM 降级（无可用 LLM 时使用规则引擎）
    llm_fallback_enabled: bool = True

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
                    "preferred_provider": "gpt4",
                    "fallback_provider": "claude",
                },
                {
                    "intent": "*",
                    "strategy": self.llm_routing_strategy,
                    "fallback_provider": "deepseek",
                },
            ]
        }


settings = Settings()
