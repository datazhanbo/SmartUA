"""
大模型路由引擎 - 支持多提供商智能路由
根据意图复杂度、数据敏感性、响应时间、成本预算选择最优模型
"""
import json
import os
import time
import httpx
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from datetime import datetime
from abc import ABC, abstractmethod


class IntentComplexity(str, Enum):
    """意图复杂度等级"""
    LOW = "low"           # 简单分类、参数提取
    MEDIUM = "medium"     # 常规分析
    HIGH = "high"         # 复杂策略分析、创意生成


class LLMCapability(str, Enum):
    """模型能力标签"""
    COMPLEX_INTENT = "complex_intent"
    STRATEGY_ANALYSIS = "strategy_analysis"
    CREATIVE_GENERATION = "creative_generation"
    FAST_RESPONSE = "fast_response"
    CODE_GENERATION = "code_generation"
    SENSITIVE_DATA = "sensitive_data"


class LLMProvider(ABC):
    """LLM Provider 抽象基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config.get("name", "unknown")
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.model = config.get("model", "default")
        self.capabilities = config.get("capabilities", [])
        self.cost_per_1k_tokens = config.get("cost_per_1k_tokens", 0)
        self.avg_latency_ms = config.get("avg_latency_ms", 1000)
        self.priority = config.get("priority", 99)
        self.type = config.get("type", "remote")  # remote / local

    @abstractmethod
    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> Dict[str, Any]:
        """调用聊天补全接口"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查 Provider 是否可用"""
        return self.api_key is not None or self.type == "local"

    def has_capability(self, capability: str) -> bool:
        """检查是否具备指定能力"""
        return capability in self.capabilities

    def calculate_score(self, required_capabilities: List[str],
                       latency_target_ms: int = 3000,
                       max_cost_per_1k: float = 10.0) -> float:
        """计算模型综合得分（越高越好）"""
        score = 0.0

        # 能力匹配得分
        matched_caps = sum(1 for cap in required_capabilities if self.has_capability(cap))
        if required_capabilities:
            score += (matched_caps / len(required_capabilities)) * 50

        # 延迟得分（越低越好）
        if self.avg_latency_ms <= latency_target_ms:
            score += 25
        else:
            score += 25 * (latency_target_ms / self.avg_latency_ms)

        # 成本得分（越低越好）
        if self.cost_per_1k_tokens <= max_cost_per_1k:
            score += 25
        else:
            score += 25 * (max_cost_per_1k / self.cost_per_1k_tokens)

        # 优先级加成
        score -= self.priority * 2

        return score


class ClaudeProvider(LLMProvider):
    """Claude 模型 Provider"""

    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> Dict[str, Any]:
        if not self.is_available():
            raise ValueError("Claude API key not configured")

        # 实际实现需要导入 anthropic SDK
        # 这里返回模拟结果（待实现）
        return {
            "provider": "claude",
            "model": self.model,
            "content": "Claude response placeholder",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}
        }

    def is_available(self) -> bool:
        return bool(self.api_key)


class GPT4Provider(LLMProvider):
    """GPT-4 模型 Provider"""

    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> Dict[str, Any]:
        if not self.is_available():
            raise ValueError("GPT API key not configured")

        # 实际实现需要导入 openai SDK
        # 这里返回模拟结果（待实现）
        return {
            "provider": "gpt4",
            "model": self.model,
            "content": "GPT-4 response placeholder",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}
        }

    def is_available(self) -> bool:
        return bool(self.api_key)


class DeepSeekProvider(LLMProvider):
    """DeepSeek 模型 Provider"""

    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> Dict[str, Any]:
        if not self.is_available():
            raise ValueError("DeepSeek API key not configured")

        # 实际实现需要导入 openai SDK 兼容模式
        # 这里返回模拟结果（待实现）
        return {
            "provider": "deepseek",
            "model": self.model,
            "content": "DeepSeek response placeholder",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}
        }

    def is_available(self) -> bool:
        return bool(self.api_key)


class ArkProvider(LLMProvider):
    """火山引擎方舟（Volcengine Ark）Provider —— 兼容 OpenAI Chat Completions 协议"""

    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000,
                            stream: bool = False) -> Any:
        if not self.is_available():
            raise ValueError("Ark API key not configured")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 推理类模型（如方舟 DeepSeek-R1 等）会先长思考再回答，且生产常经代理出网，
        # 故放宽超时并显式带代理环境变量，避免 ReadTimeout。
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        client_kwargs = dict(
            proxy=proxy,
            timeout=httpx.Timeout(180.0, connect=15.0),
            trust_env=True,
        )

        if stream:
            # 流式：逐块 yield {"type":"reasoning"/"content","text": delta}，供 Agent Loop 实时填充思考步骤
            async def _gen():
                async with httpx.AsyncClient(**client_kwargs) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload_str = line[len("data:"):].strip()
                            if payload_str == "[DONE]":
                                break
                            try:
                                obj = json.loads(payload_str)
                            except Exception:
                                continue
                            choices = obj.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            if delta.get("reasoning_content"):
                                yield {"type": "reasoning", "text": delta["reasoning_content"]}
                            if delta.get("content"):
                                yield {"type": "content", "text": delta["content"]}
            return _gen()

        # 非流式：返回完整结果，并捕获推理模型的 reasoning_content（思考过程）
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        usage = data.get("usage", {})
        return {
            "provider": "ark",
            "model": self.model,
            "content": content,
            "reasoning": reasoning,
            "usage": usage,
        }

    def is_available(self) -> bool:
        return bool(self.api_key)


class LocalModelProvider(LLMProvider):
    """本地模型 Provider（如 Qwen、Llama 等）"""

    async def chat_completion(self, messages: List[Dict[str, str]],
                            temperature: float = 0.7,
                            max_tokens: int = 1000) -> Dict[str, Any]:
        if not self.is_available():
            raise ValueError("Local model not configured")

        # 实际实现需要调用本地 inference 服务
        # 这里返回模拟结果（待实现）
        return {
            "provider": "local",
            "model": self.model,
            "content": "Local model response placeholder",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}
        }

    def is_available(self) -> bool:
        return self.type == "local"


class LLMRouter:
    """大模型路由引擎"""

    # 意图到能力需求映射
    INTENT_CAPABILITY_MAP = {
        "campaign.pause": [LLMCapability.FAST_RESPONSE],
        "campaign.resume": [LLMCapability.FAST_RESPONSE],
        "campaign.budget_adjust": [LLMCapability.FAST_RESPONSE],
        "campaign.bid_adjust": [LLMCapability.FAST_RESPONSE],
        "campaign.optimize_batch": [LLMCapability.COMPLEX_INTENT, LLMCapability.STRATEGY_ANALYSIS],
        "creative.rotate": [LLMCapability.CREATIVE_GENERATION, LLMCapability.FAST_RESPONSE],
        "alert.review": [LLMCapability.FAST_RESPONSE],
        "report.generate": [LLMCapability.FAST_RESPONSE],
    }

    # 意图复杂度映射
    INTENT_COMPLEXITY_MAP = {
        "campaign.pause": IntentComplexity.LOW,
        "campaign.resume": IntentComplexity.LOW,
        "campaign.budget_adjust": IntentComplexity.MEDIUM,
        "campaign.bid_adjust": IntentComplexity.MEDIUM,
        "campaign.optimize_batch": IntentComplexity.HIGH,
        "creative.rotate": IntentComplexity.HIGH,
        "alert.review": IntentComplexity.LOW,
        "report.generate": IntentComplexity.MEDIUM,
    }

    def __init__(self, providers_config: Dict[str, Any]):
        self.providers: Dict[str, LLMProvider] = {}
        self.routing_rules = providers_config.get("routing_rules", [])
        self._initialize_providers(providers_config.get("providers", {}))

    def _initialize_providers(self, providers_config: Dict[str, Any]):
        """初始化所有 Provider"""
        provider_classes = {
            "claude": ClaudeProvider,
            "gpt4": GPT4Provider,
            "deepseek": DeepSeekProvider,
            "ark": ArkProvider,
            "local": LocalModelProvider,
        }

        for provider_id, config in providers_config.items():
            provider_type = config.get("provider_type", provider_id)
            if provider_type in provider_classes:
                provider_class = provider_classes[provider_type]
                self.providers[provider_id] = provider_class(config)

    def get_available_providers(self) -> List[Tuple[str, LLMProvider]]:
        """获取所有可用的 Provider"""
        return [(pid, p) for pid, p in self.providers.items() if p.is_available()]

    def route(self, intent_type: str,
             data_sensitivity: str = "low",
             strategy: str = "best_fit") -> Optional[str]:
        """
        路由决策：选择最优模型

        Args:
            intent_type: 意图类型
            data_sensitivity: 数据敏感性 low/medium/high
            strategy: 路由策略 best_fit / fastest / least_cost / highest_quality

        Returns:
            选中的 provider ID，None 表示无可选模型
        """
        available = self.get_available_providers()
        if not available:
            return None

        # 高敏感数据优先使用本地模型
        if data_sensitivity == "high":
            for pid, provider in available:
                if provider.type == "local" and provider.has_capability(LLMCapability.SENSITIVE_DATA):
                    return pid

        # 获取意图所需能力
        required_caps = self.INTENT_CAPABILITY_MAP.get(intent_type, [LLMCapability.FAST_RESPONSE])

        # 检查是否有预定义路由规则
        for rule in self.routing_rules:
            if rule.get("intent") == intent_type or rule.get("intent") == "*":
                preferred = rule.get("preferred_provider")
                if preferred in self.providers and self.providers[preferred].is_available():
                    # 检查能力匹配
                    if all(self.providers[preferred].has_capability(cap) for cap in required_caps):
                        return preferred
                fallback = rule.get("fallback_provider")
                if fallback in self.providers and self.providers[fallback].is_available():
                    return fallback

        # 根据策略选择
        if strategy == "fastest":
            # 最快响应
            available.sort(key=lambda x: x[1].avg_latency_ms)
            return available[0][0]

        elif strategy == "least_cost":
            # 最低成本
            available.sort(key=lambda x: x[1].cost_per_1k_tokens)
            return available[0][0]

        elif strategy == "highest_quality":
            # 最高质量（按优先级）
            available.sort(key=lambda x: x[1].priority)
            return available[0][0]

        else:  # best_fit
            # 综合得分最高
            scored = []
            for pid, provider in available:
                score = provider.calculate_score(required_caps)
                scored.append((score, pid))
            scored.sort(reverse=True)
            return scored[0][1] if scored else None

    async def chat_completion(self, intent_type: str, messages: List[Dict[str, str]],
                            data_sensitivity: str = "low",
                            fallback_to_any: bool = True,
                            **kwargs) -> Dict[str, Any]:
        """
        智能路由并调用聊天补全

        Args:
            intent_type: 意图类型
            messages: 对话消息
            data_sensitivity: 数据敏感性
            fallback_to_any: 首选失败时是否尝试其他可用模型
            **kwargs: 传递给 provider 的参数

        Returns:
            调用结果
        """
        provider_id = self.route(intent_type, data_sensitivity)

        if not provider_id:
            # 无可选 Provider，返回降级模式标志
            return {
                "provider": "none",
                "model": "fallback_rule_based",
                "content": None,
                "fallback_mode": True,
                "message": "No LLM available, using rule-based fallback"
            }

        stream = kwargs.pop("stream", False)
        provider = self.providers[provider_id]

        # 流式：优先在主 provider 上尝试（仅 Ark 等支持的 provider 会返回 async generator）
        if stream:
            try:
                return await provider.chat_completion(messages, stream=True, **kwargs)
            except Exception:
                pass  # 主 provider 流式失败，落到下方非流式兜底

        # 尝试调用首选（非流式）
        try:
            result = await provider.chat_completion(messages, **kwargs)
            result["routed_provider"] = provider_id
            return result
        except Exception as e:
            if fallback_to_any:
                # 降级尝试其他可用 Provider
                for pid, provider in self.get_available_providers():
                    if pid == provider_id:
                        continue
                    try:
                        result = await provider.chat_completion(messages, **kwargs)
                        result["routed_provider"] = pid
                        result["fallback_from"] = provider_id
                        return result
                    except:
                        continue

            # 全部失败，返回降级模式
            return {
                "provider": "none",
                "model": "fallback_rule_based",
                "content": None,
                "fallback_mode": True,
                "message": f"LLM call failed: {str(e)}"
            }

    def get_provider_status(self) -> Dict[str, Any]:
        """获取所有 Provider 状态"""
        status = {}
        for pid, provider in self.providers.items():
            status[pid] = {
                "name": provider.name,
                "available": provider.is_available(),
                "capabilities": provider.capabilities,
                "avg_latency_ms": provider.avg_latency_ms,
                "cost_per_1k_tokens": provider.cost_per_1k_tokens,
                "priority": provider.priority,
            }
        return status


# 全局路由实例（单例模式）
_global_router: Optional[LLMRouter] = None


def get_llm_router(config: Optional[Dict[str, Any]] = None) -> LLMRouter:
    """获取全局 LLM Router 实例"""
    global _global_router

    if _global_router is None and config is not None:
        _global_router = LLMRouter(config)

    return _global_router


def is_llm_available() -> bool:
    """检查是否有可用的 LLM"""
    router = get_llm_router()
    if router is None:
        return False
    return len(router.get_available_providers()) > 0
