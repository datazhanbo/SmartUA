from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.core.security import (
    verify_password, create_access_token, get_current_user,
    get_user_permissions, get_user_apps
)
from app.models.sys import User, Role, UserAppBinding
from app.schemas.auth import (
    Token, UserResponse, UserWithApps, LoginRequest
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(
    form_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """用户登录（JSON格式）"""
    user = db.query(User).filter(User.email == form_data.email).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active"
        )

    # 更新最后登录时间
    user.last_login_at = datetime.utcnow()
    db.commit()

    access_token_expires = timedelta(minutes=60 * 24)  # 24小时
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    return Token(
        access_token=access_token,
        expires_at=datetime.utcnow() + access_token_expires
    )


@router.post("/login/form", response_model=Token)
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """用户登录（form格式，兼容Swagger UI）"""
    return await login(
        LoginRequest(email=form_data.username, password=form_data.password),
        db
    )


@router.get("/me", response_model=UserWithApps)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户信息"""
    roles = db.query(Role).join(User.roles).filter(User.id == current_user.id).all()
    apps = get_user_apps(current_user, db)

    return UserWithApps(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        phone=current_user.phone,
        department=current_user.department,
        status=current_user.status,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        roles=[r.name for r in roles],
        apps=apps
    )


@router.get("/permissions")
async def get_permissions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户的权限列表"""
    permissions = get_user_permissions(current_user, db)
    return {"permissions": permissions}
