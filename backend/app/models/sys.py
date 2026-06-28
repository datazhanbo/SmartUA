from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, BigInteger, Text, ARRAY, Numeric, Table
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base

# 用户-角色多对多关联表
user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True)
)

# 角色-权限多对多关联表
role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True)
)


class App(Base):
    """多租户App表"""
    __tablename__ = "apps"

    id = Column(Integer, primary_key=True, index=True)
    app_key = Column(String(64), unique=True, nullable=False, index=True)
    app_name = Column(String(128), nullable=False)
    app_type = Column(String(32), default="game")
    platform = Column(String(16))
    icon_url = Column(Text)
    timezone = Column(String(32), default="Asia/Shanghai")
    currency = Column(String(8), default="USD")
    status = Column(String(16), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user_bindings = relationship("UserAppBinding", back_populates="app", cascade="all, delete-orphan")


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=False)
    password_hash = Column(String(255), nullable=False)
    avatar_url = Column(Text)
    phone = Column(String(32))
    department = Column(String(64))
    status = Column(String(16), default="active")
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    app_bindings = relationship("UserAppBinding", back_populates="user", cascade="all, delete-orphan")


class Role(Base):
    """角色表"""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), unique=True, nullable=False)
    label = Column(String(64), nullable=False)
    description = Column(Text)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")


class Permission(Base):
    """权限表"""
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(128), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    module = Column(String(32), nullable=False)
    action = Column(String(16), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


class UserAppBinding(Base):
    """用户-App绑定表（数据权限）"""
    __tablename__ = "user_app_bindings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    app_id = Column(Integer, ForeignKey("apps.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="app_bindings")
    app = relationship("App", back_populates="user_bindings")


class AuditLog(Base):
    """审计日志"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(Integer, ForeignKey("apps.id"))
    action = Column(String(64), nullable=False)
    module = Column(String(32), nullable=False)
    resource_type = Column(String(32))
    resource_id = Column(String(64))
    detail = Column(JSON)
    ip_address = Column(String(64))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Menu(Base):
    """菜单表"""
    __tablename__ = "menus"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("menus.id"))
    code = Column(String(64), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    path = Column(String(128))
    icon = Column(String(64))
    sort_order = Column(Integer, default=0)
    permissions = Column(JSON)  # SQLite用JSON代替ARRAY
    visible_roles = Column(JSON)
    is_active = Column(Boolean, default=True)


# 需要先定义Table再导入Model，所以这里放后面
from sqlalchemy import Table
