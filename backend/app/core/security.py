from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import settings
from app.db.base import get_db
from app.models.sys import User, UserAppBinding, Role, Permission, role_permissions

# 使用sha256_crypt代替bcrypt，避免72字节限制
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User account is not active")
    return user


def get_user_permissions(user: User, db: Session) -> List[str]:
    """获取用户所有权限码"""
    roles = db.query(Role).join(User.roles).filter(User.id == user.id).all()
    role_ids = [r.id for r in roles]
    perms = db.query(Permission).join(role_permissions).filter(role_permissions.c.role_id.in_(role_ids)).all()
    return [p.code for p in perms]


def get_user_apps(user: User, db: Session) -> List[dict]:
    """获取用户有权限的App列表"""
    bindings = db.query(UserAppBinding).filter(UserAppBinding.user_id == user.id).all()
    return [
        {"id": b.app_id, "role_id": b.role_id, "is_default": b.is_default}
        for b in bindings
    ]


def user_can_access_app(user: User, app_id: int, db: Session) -> bool:
    """Phase 2.1：用户对某 app 是否有访问权限（基于 UserAppBinding）。

    单一来源判断，供 Agent / 自治 / 策略等所有以 app_id 为租户边界的端点复用。
    system-generated 会话（user_id 为负数占位）不视为归属，不由此函数管辖。
    """
    if user is None or app_id is None:
        return False
    return db.query(UserAppBinding).filter(
        UserAppBinding.user_id == user.id,
        UserAppBinding.app_id == app_id,
    ).first() is not None


def require_app_access(user: User, app_id: int, db: Session) -> None:
    """Phase 2.1：断言用户对 app 有权限；否则抛 404（避免对象枚举）。

    统一返回 404 是刻意选择：与其暴露 "app 存在但你没权限" 的 403，不如让攻击者
    无法从响应中区分 "不存在" 与 "存在但拒绝"，堵住枚举侧信道。
    """
    if not user_can_access_app(user, app_id, db):
        raise HTTPException(status_code=404, detail="Not found")
