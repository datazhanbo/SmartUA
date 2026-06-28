from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date


class AppBase(BaseModel):
    app_key: str
    app_name: str
    app_type: Optional[str] = "game"
    platform: Optional[str] = None
    icon_url: Optional[str] = None
    timezone: Optional[str] = "Asia/Shanghai"
    currency: Optional[str] = "USD"


class AppCreate(AppBase):
    pass


class AppUpdate(BaseModel):
    app_name: Optional[str] = None
    app_type: Optional[str] = None
    platform: Optional[str] = None
    icon_url: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    status: Optional[str] = None


class AppResponse(AppBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserAppBindingCreate(BaseModel):
    user_id: int
    app_id: int
    role_id: int
    is_default: Optional[bool] = False


class AppSwitchRequest(BaseModel):
    app_id: int
