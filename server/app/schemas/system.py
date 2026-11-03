from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ==================== 字典类型 Schema ====================


class SysDictBase(BaseModel):
    dict_name: str = Field(..., min_length=1, max_length=64)
    dict_code: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=255)
    status: int = Field(default=1, ge=0, le=1)
    sort: int = Field(default=0)


class SysDictCreate(BaseModel):
    dict_name: str = Field(..., min_length=1, max_length=64)
    dict_code: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=255)
    status: int = Field(default=1, ge=0, le=1)
    sort: int = Field(default=0)


class SysDictUpdate(BaseModel):
    dict_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    dict_code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=255)
    status: Optional[int] = Field(default=None, ge=0, le=1)
    sort: Optional[int] = Field(default=None)


class SysDictOut(BaseModel):
    id: int
    dict_name: str
    dict_code: str
    description: Optional[str]
    status: int
    sort: int
    is_deleted: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 字典项 Schema ====================


class SysDictItemBase(BaseModel):
    dict_code: str = Field(..., min_length=1, max_length=64)
    dict_label: str = Field(..., min_length=1, max_length=64)
    dict_value: str = Field(..., min_length=1, max_length=255)
    sort: int = Field(default=0)
    status: int = Field(default=1, ge=0, le=1)


class SysDictItemCreate(BaseModel):
    dict_code: str = Field(..., min_length=1, max_length=64)
    dict_label: str = Field(..., min_length=1, max_length=64)
    dict_value: str = Field(..., min_length=1, max_length=255)
    sort: int = Field(default=0)
    status: int = Field(default=1, ge=0, le=1)


class SysDictItemUpdate(BaseModel):
    dict_code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    dict_label: Optional[str] = Field(default=None, min_length=1, max_length=64)
    dict_value: Optional[str] = Field(default=None, min_length=1, max_length=255)
    sort: Optional[int] = Field(default=None)
    status: Optional[int] = Field(default=None, ge=0, le=1)


class SysDictItemOut(BaseModel):
    id: int
    dict_code: str
    dict_label: str
    dict_value: str
    sort: int
    status: int
    is_deleted: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ==================== 用户管理 Schema ====================


class SysUserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    status: int = Field(default=1, ge=0, le=1)
    role_ids: List[int] = Field(default_factory=list, comment="角色ID列表")


class SysUserUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=128)
    status: Optional[int] = Field(default=None, ge=0, le=1)
    role_ids: Optional[List[int]] = Field(default=None, comment="角色ID列表")


class SysUserResetPassword(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class SysUserOut(BaseModel):
    id: int
    username: str
    nickname: Optional[str] = None
    email: Optional[str] = None
    status: int
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    roles: List[str] = Field(default_factory=list)
    role_ids: List[int] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ==================== 角色管理 Schema ====================


class SysRoleCreate(BaseModel):
    role_code: str = Field(..., min_length=2, max_length=32)
    role_name: str = Field(..., min_length=1, max_length=64)
    permissions: List[str] = Field(default_factory=list)


class SysRoleUpdate(BaseModel):
    role_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    permissions: Optional[List[str]] = None


class SysRoleOut(BaseModel):
    id: int
    role_code: str
    role_name: str
    permissions: List[str] = Field(default_factory=list)
    user_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== 权限点 Schema ====================


class PermissionItemOut(BaseModel):
    code: str
    name: str


class PermissionGroupOut(BaseModel):
    group: str
    items: List[PermissionItemOut] = Field(default_factory=list)


# ==================== 操作日志 Schema ====================


class OperationLogOut(BaseModel):
    id: int
    operator: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    before_json: Optional[dict] = None
    after_json: Optional[dict] = None
    ip: Optional[str] = None
    trace_id: Optional[str] = None
    result: str
    created_at: datetime

    model_config = {"from_attributes": True}