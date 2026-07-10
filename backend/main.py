"""
SmartUA - 智能投放平台
核心能力：大模型意图识别驱动投放、操作安全分级控制、闭环学习优化
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db.base import engine, Base
from app.api.v1 import auth, apps, data, intent, llm, data_management, connectors, campaign as campaign_router, agent as agent_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smartua")

# 创建数据库表
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：若开启主动自治，拉起 APScheduler 后台周期巡检
    if settings.agent_autonomy_enabled:
        try:
            from app.services.agent_runtime.autonomy import start_scheduler
            start_scheduler()
        except Exception as e:
            logger.warning("主动自治调度启动失败：%s", e)
    yield
    # 关闭：停掉调度器
    try:
        from app.services.agent_runtime.autonomy import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="SmartUA Platform API",
    description="智能投放平台 - 支持大模型意图识别、操作安全分级控制、闭环学习优化（迈向 Agentic）",
    version="1.6.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境，生产环境需要限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(auth.router, prefix="/api/v1")
app.include_router(apps.router, prefix="/api/v1")
app.include_router(data.router, prefix="/api/v1")
app.include_router(intent.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(data_management.router, prefix="/api/v1")
app.include_router(connectors.router, prefix="/api/v1")
app.include_router(campaign_router.router, prefix="/api/v1")
app.include_router(agent_router.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "name": "SmartUA Platform API",
        "version": "1.6.0",
        "description": "智能投放平台 - 大模型驱动的投放优化系统（迈向 Agentic Ad Platform）",
        "features": [
            "大模型意图识别（自然语言 -> 投放操作）",
            "操作安全分级（L0自动 / L1一键确认 / L2人工审核 / L3仅建议）",
            "多App数据隔离",
            "Campaign健康度自动评分",
            "异常预警引擎",
            "策略模板库",
            "效果闭环学习",
            "主动式自治（APScheduler 周期巡检 + 分级处置，Phase 4）",
        ],
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "env": settings.env}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
