from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.db.base import get_db
from app.core.security import get_current_user
from app.models.sys import App, User, UserAppBinding
from app.schemas.app import (
    AppResponse, AppCreate, AppUpdate,
    UserAppBindingCreate, AppSwitchRequest
)

router = APIRouter(prefix="/apps", tags=["apps"])


@router.get("/", response_model=List[AppResponse])
async def get_user_apps(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户有权限的App列表"""
    bindings = db.query(UserAppBinding).filter(
        UserAppBinding.user_id == current_user.id
    ).all()
    app_ids = [b.app_id for b in bindings]
    apps = db.query(App).filter(App.id.in_(app_ids)).all()
    return apps


@router.get("/{app_id}", response_model=AppResponse)
async def get_app(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取App详情"""
    binding = db.query(UserAppBinding).filter(
        UserAppBinding.user_id == current_user.id,
        UserAppBinding.app_id == app_id
    ).first()
    if not binding:
        raise HTTPException(status_code=403, detail="No access to this app")

    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return app


@router.post("/", response_model=AppResponse, status_code=status.HTTP_201_CREATED)
async def create_app(
    app_data: AppCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新App（仅管理员）"""
    # TODO: 检查管理员权限
    existing = db.query(App).filter(App.app_key == app_data.app_key).first()
    if existing:
        raise HTTPException(status_code=400, detail="App key already exists")

    app = App(**app_data.model_dump())
    db.add(app)
    db.commit()
    db.refresh(app)

    # 自动绑定给创建者
    binding = UserAppBinding(
        user_id=current_user.id,
        app_id=app.id,
        role_id=1,  # 假设Admin角色ID为1
        is_default=True
    )
    db.add(binding)
    db.commit()

    return app


@router.put("/{app_id}", response_model=AppResponse)
async def update_app(
    app_id: int,
    app_data: AppUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新App信息"""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    for field, value in app_data.model_dump(exclude_unset=True).items():
        setattr(app, field, value)
    db.commit()
    db.refresh(app)
    return app
