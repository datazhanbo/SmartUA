from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional, List, Dict, Any

from app.db.base import get_db
from app.api.v1.auth import get_current_user
from app.models.sys import User
from app.core.security import get_user_apps
from app.services.connector_service import ConnectorService
from app.schemas.data import (
    ConnectorCredentialCreate,
    ConnectorCredentialUpdate,
    ConnectorCredentialResponse,
    ConnectorCredentialSimpleResponse,
    ConnectorVerifyRequest
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _get_app_id(user: User, db: Session) -> int:
    """获取用户关联的 app_id"""
    apps = get_user_apps(user, db)
    if not apps:
        return 1  # 默认 app_id
    return apps[0]["id"]


@router.get("/")
def list_connectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取可用的连接器列表"""
    service = ConnectorService(db)
    return service.list_connectors()


@router.get("/runs")
def list_connector_runs(
    connector: Optional[str] = Query(None, description="按平台过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取连接器运行历史"""
    service = ConnectorService(db)
    return service.list_connector_runs(
        app_id=_get_app_id(current_user, db),
        connector=connector,
        status=status,
        limit=limit,
        offset=offset
    )


@router.post("/pull")
def run_pull(
    platform: str,
    date_from: date,
    date_to: date,
    report_type: str = Query("campaign_daily", description="报表类型"),
    account_id: Optional[str] = Query("", description="广告账号ID"),
    app_key: Optional[str] = Query("", description="应用标识"),
    credentials: Optional[Dict] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """运行数据拉取任务"""
    service = ConnectorService(db)
    result = service.run_pull(
        app_id=_get_app_id(current_user, db),
        platform=platform,
        date_from=date_from,
        date_to=date_to,
        report_type=report_type,
        credentials=credentials,
        account_id=account_id,
        app_key=app_key,
        executed_by=current_user.id
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Pull failed"))

    return result


@router.post("/operation")
def run_operation(
    platform: str,
    operation: str,
    entity_id: str,
    params: Dict[str, Any],
    credentials: Optional[Dict] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """执行写操作（更新预算、出价、状态等）"""
    service = ConnectorService(db)
    result = service.run_operation(
        app_id=_get_app_id(current_user, db),
        platform=platform,
        operation=operation,
        entity_id=entity_id,
        params=params,
        credentials=credentials,
        executed_by=current_user.id
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Operation failed"))

    return result


@router.post("/sync/dws")
def sync_dws(
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """同步 DWD 到 DWS 聚合层"""
    service = ConnectorService(db)
    result = service.sync_dwd_to_dws(
        app_id=_get_app_id(current_user, db),
        date_from=date_from,
        date_to=date_to
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Sync failed"))

    return result


@router.get("/status")
def get_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取同步状态概览"""
    service = ConnectorService(db)
    return service.get_sync_status(app_id=_get_app_id(current_user, db))


# === 凭证管理 ===

@router.get("/credentials", response_model=List[ConnectorCredentialSimpleResponse])
def list_credentials(
    platform: Optional[str] = Query(None, description="按平台过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取凭证列表"""
    service = ConnectorService(db)
    return service.list_credentials(app_id=_get_app_id(current_user, db), platform=platform)


@router.get("/credentials/{credential_id}", response_model=ConnectorCredentialResponse)
def get_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取单个凭证详情"""
    service = ConnectorService(db)
    credential = service.get_credential(app_id=_get_app_id(current_user, db), credential_id=credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


@router.post("/credentials", response_model=ConnectorCredentialResponse)
def create_credential(
    data: ConnectorCredentialCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建新凭证"""
    service = ConnectorService(db)
    return service.create_credential(app_id=_get_app_id(current_user, db), data=data)


@router.put("/credentials/{credential_id}", response_model=ConnectorCredentialResponse)
def update_credential(
    credential_id: int,
    data: ConnectorCredentialUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新凭证"""
    service = ConnectorService(db)
    credential = service.update_credential(
        app_id=_get_app_id(current_user, db),
        credential_id=credential_id,
        data=data
    )
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


@router.delete("/credentials/{credential_id}")
def delete_credential(
    credential_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """删除凭证"""
    service = ConnectorService(db)
    success = service.delete_credential(app_id=_get_app_id(current_user, db), credential_id=credential_id)
    if not success:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"success": True, "message": "Credential deleted"}


@router.post("/credentials/verify")
def verify_credential(
    request: ConnectorVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """验证凭证有效性"""
    service = ConnectorService(db)
    result = service.verify_credential(
        app_id=_get_app_id(current_user, db),
        credential_id=request.credential_id
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Verification failed"))
    return result
