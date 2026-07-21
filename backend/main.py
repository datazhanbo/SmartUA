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
from app.models import agent_runtime as _agent_runtime_models  # noqa: F401  注册 Agent 运行时持久化表到 Base.metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smartua")

# ── Schema 迁移检查 ────────────────────────────────────────────────────
# Phase 0.2: 启动时检查 Alembic 迁移版本。
# - 若库中已有 alembic_version 表（即已迁移），则验证当前 revision 为 head；
# - 若库中无任何表（全新库），则通过 create_all() 建表并 stamp 为 head；
# - 若库中有业务表但无 alembic_version（从 v1.8 之前升级），则通过 create_all()
#   补齐缺失表并 stamp 为 head，保证数据不丢失。
# 过渡期结束后（所有环境均经过一次迁移），可移除 create_all() 回退，仅保留迁移检查。
def _ensure_schema() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    has_alembic_version = "alembic_version" in existing_tables

    if has_alembic_version:
        # 已迁移库：验证 revision 为 head
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            alembic_cfg = Config("alembic.ini")
            script = ScriptDirectory.from_config(alembic_cfg)
            head_revision = script.get_current_head()

            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if row == head_revision:
                logger.info("Schema 迁移版本验证通过: %s", row)
                return
            else:
                logger.warning(
                    "Schema 迁移版本不匹配: 当前 %s, 期望 %s。尝试 upgrade...",
                    row, head_revision,
                )
                _run_alembic_upgrade()
        except Exception as exc:
            logger.warning("Alembic 版本检查失败: %s", exc)
            logger.warning("create_all() 回退建表...")
            Base.metadata.create_all(bind=engine)
    elif existing_tables:
        # 有业务表但无迁移版本：从 v1.8 之前升级，stamp 为 head
        logger.info(
            "检测到 %d 张业务表但无 alembic_version，执行 create_all() 补齐 + stamp",
            len(existing_tables),
        )
        Base.metadata.create_all(bind=engine)
        _stamp_head()
    else:
        # 全新空库：create_all() 建表 + stamp
        logger.info("全新空库，create_all() 建表 + stamp head")
        Base.metadata.create_all(bind=engine)
        _stamp_head()


def _run_alembic_upgrade() -> None:
    from alembic.config import CommandLine
    CommandLine().run(["alembic", "upgrade", "head"])


def _stamp_head() -> None:
    """Stamp the current database as at the Alembic head revision."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.command import stamp

    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()
    if head:
        stamp(alembic_cfg, head)
        logger.info("Schema 已 stamp 为 %s", head)


_ensure_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化 LLM 路由（配置好 key 后 Agent Loop 即可调用真实大模型）
    try:
        from app.services.llm import get_llm_router
        get_llm_router(settings.get_llm_providers_config())
    except Exception as e:
        logger.warning("LLM 路由初始化失败（将使用规则引擎兜底）：%s", e)

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
    version="1.8.0",
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
        "version": "1.8.0",
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
