from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class TokenData(BaseModel):
    email: Optional[str] = None


class UserBase(BaseModel):
    email: EmailStr
    username: str
    phone: Optional[str] = None
    department: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    status: Optional[str] = None


class UserResponse(UserBase):
    id: int
    status: str
    last_login_at: Optional[datetime] = None
    created_at: datetime
    roles: List[str] = []

    class Config:
        from_attributes = True


class UserWithApps(UserResponse):
    apps: List[dict] = []


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RoleBase(BaseModel):
    name: str
    label: str
    description: Optional[str] = None


class RoleResponse(RoleBase):
    id: int
    is_system: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PermissionBase(BaseModel):
    code: str
    name: str
    module: str
    action: str


class PermissionResponse(PermissionBase):
    id: int

    class Config:
        from_attributes = True
