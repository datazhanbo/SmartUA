"""
大模型路由 API - 查看 LLM Provider 状态、测试路由
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any
from app.db.base import get_db
from app.core.security import get_current_user
from app.models.sys import User
from app.services.llm import get_llm_router, is_llm_available
from app.config import settings

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
async def get_llm_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取 LLM 路由状态和各 Provider 可用性"""
    config = settings.get_llm_providers_config()
    router = get_llm_router(config)

    return {
        "llm_available": is_llm_available(),
        "routing_strategy": settings.llm_routing_strategy,
        "fallback_enabled": settings.llm_fallback_enabled,
        "providers": router.get_provider_status() if router else {},
    }


@router.post("/test-route")
async def test_llm_routing(
    intent_type: str,
    data_sensitivity: str = "low",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """测试路由决策，返回选中的 Provider"""
    config = settings.get_llm_providers_config()
    router = get_llm_router(config)

    if not router:
        raise HTTPException(status_code=500, detail="LLM router not initialized")

    selected = router.route(intent_type, data_sensitivity)
    available = router.get_available_providers()

    return {
        "intent_type": intent_type,
        "data_sensitivity": data_sensitivity,
        "selected_provider": selected,
        "available_providers": [pid for pid, _ in available],
    }


@router.get("/intent-capabilities")
async def get_intent_capabilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取各意图类型所需的模型能力映射"""
    from app.services.llm.router import LLMRouter

    return {
        "intent_capability_map": LLMRouter.INTENT_CAPABILITY_MAP,
        "intent_complexity_map": LLMRouter.INTENT_COMPLEXITY_MAP,
    }
