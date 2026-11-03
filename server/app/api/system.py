from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.response import ok
from app.schemas.system import (
    OperationLogOut,
    SysDictCreate,
    SysDictOut,
    SysDictItemCreate,
    SysDictItemOut,
    SysDictItemUpdate,
    SysDictUpdate,
    SysRoleCreate,
    SysRoleUpdate,
    SysUserCreate,
    SysUserResetPassword,
    SysUserUpdate,
)
from app.service import system as system_service

router = APIRouter(prefix="/api/system", tags=["系统配置"])


# ==================== 字典类型表 SysDict ====================

@router.get("/dict", response_model=None)
def list_dicts(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: Optional[str] = Query(default=None),
):
    """分页查询字典类型（权限：system:dict:read）。"""
    items, total = system_service.list_dicts(
        db=db,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    return ok({"items": [SysDictOut.model_validate(c).model_dump() for c in items], "total": total, "page": page, "page_size": page_size})


@router.post("/dict", response_model=None)
def create_dict(
    data: SysDictCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """新增字典类型（权限：system:dict:write）。"""
    dict_item = system_service.create_dict(db=db, data=data)
    return ok(SysDictOut.model_validate(dict_item).model_dump())


@router.put("/dict/{dict_code}", response_model=None)
def update_dict(
    dict_code: str,
    data: SysDictUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """更新字典类型（权限：system:dict:write）。"""
    dictionary = system_service.update_dict(db=db, dict_code=dict_code, data=data)
    if not dictionary:
        return ok({"message": "字典类型不存在"}, code=404)
    return ok(SysDictOut.model_validate(dictionary).model_dump())


@router.delete("/dict/{dict_code}", response_model=None)
def delete_dict(
    dict_code: str,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """删除字典类型（级联删除字典项，权限：system:dict:write）。"""
    deleted = system_service.delete_dict(db=db, dict_code=dict_code)
    if not deleted:
        return ok({"message": "字典类型不存在"}, code=404)
    return ok({"deleted": True})


# ==================== 字典项表 SysDictItem ====================

@router.get("/dict/{dict_code}/items", response_model=None)
def list_dict_items(
    dict_code: str,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: Optional[int] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
):
    """分页查询字典项（权限：system:dict:read）。"""
    items, total = system_service.list_dict_items(
        db=db,
        dict_code=dict_code,
        page=page,
        page_size=page_size,
        status=status,
        keyword=keyword,
    )
    return ok({"items": [SysDictItemOut.model_validate(i).model_dump() for i in items], "total": total, "page": page, "page_size": page_size})


@router.post("/dict/{dict_code}/items", response_model=None)
def create_dict_item(
    dict_code: str,
    data: SysDictItemCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """新增字典项（权限：system:dict:write）。"""
    item = system_service.create_dict_item(db=db, dict_code=dict_code, data=data)
    return ok(SysDictItemOut.model_validate(item).model_dump())


@router.put("/dict/{dict_code}/items/{item_id}", response_model=None)
def update_dict_item(
    dict_code: str,
    item_id: int,
    data: SysDictItemUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """更新字典项（权限：system:dict:write）。"""
    item = system_service.update_dict_item(db=db, item_id=item_id, data=data)
    if not item:
        return ok({"message": "字典项不存在"}, code=404)
    return ok(SysDictItemOut.model_validate(item).model_dump())


@router.delete("/dict/{dict_code}/items/{item_id}", response_model=None)
def delete_dict_item(
    dict_code: str,
    item_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:dict:write")),
):
    """删除字典项（权限：system:dict:write）。"""
    deleted = system_service.delete_dict_item(db=db, item_id=item_id)
    if not deleted:
        return ok({"message": "字典项不存在"}, code=404)
    return ok({"deleted": True})


# ==================== 权限点目录 ====================

@router.get("/permissions", response_model=None)
def list_permissions(
    user: CurrentUser,
    _: None = Depends(require_perm("system:role:read")),
):
    """权限点目录（按业务分组，权限：system:role:read）。"""
    groups = system_service.list_permission_groups()
    return ok([g.model_dump() for g in groups])


# ==================== 用户管理 ====================

@router.get("/users", response_model=None)
def list_users(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: Optional[str] = Query(default=None),
    status: Optional[int] = Query(default=None),
):
    """分页查询用户（权限：system:user:read）。"""
    items, total = system_service.SysUserService.list_users(
        db=db, page=page, page_size=page_size, keyword=keyword, status=status
    )
    return ok(
        {
            "items": [u.model_dump() for u in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/users", response_model=None)
def create_user(
    data: SysUserCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:write")),
):
    """新增用户（权限：system:user:write）。"""
    created = system_service.SysUserService.create_user(db=db, data=data)
    return ok(created.model_dump())


@router.get("/users/{user_id}", response_model=None)
def get_user(
    user_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:read")),
):
    """用户详情（权限：system:user:read）。"""
    detail = system_service.SysUserService.get_user(db=db, user_id=user_id)
    return ok(detail.model_dump())


@router.put("/users/{user_id}", response_model=None)
def update_user(
    user_id: int,
    data: SysUserUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:write")),
):
    """修改用户（权限：system:user:write）。"""
    updated = system_service.SysUserService.update_user(
        db=db, user_id=user_id, data=data
    )
    return ok(updated.model_dump())


@router.delete("/users/{user_id}", response_model=None)
def delete_user(
    user_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:write")),
):
    """删除用户（权限：system:user:write）。"""
    system_service.SysUserService.delete_user(
        db=db, user_id=user_id, current_user_id=user.id
    )
    return ok({"deleted": True})


@router.post("/users/{user_id}/reset-password", response_model=None)
def reset_user_password(
    user_id: int,
    data: SysUserResetPassword,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:user:write")),
):
    """重置用户密码（权限：system:user:write）。"""
    system_service.SysUserService.reset_password(
        db=db, user_id=user_id, password=data.password
    )
    return ok({"reset": True})


# ==================== 角色权限管理 ====================

@router.get("/roles", response_model=None)
def list_roles(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:role:read")),
    keyword: Optional[str] = Query(default=None),
):
    """角色列表（权限：system:role:read）。"""
    roles = system_service.SysRoleService.list_roles(db=db, keyword=keyword)
    return ok({"items": [r.model_dump() for r in roles], "total": len(roles)})


@router.post("/roles", response_model=None)
def create_role(
    data: SysRoleCreate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:role:write")),
):
    """新增角色（权限：system:role:write）。"""
    role = system_service.SysRoleService.create_role(db=db, data=data)
    return ok(role.model_dump())


@router.put("/roles/{role_id}", response_model=None)
def update_role(
    role_id: int,
    data: SysRoleUpdate,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:role:write")),
):
    """修改角色与权限点（权限：system:role:write）。"""
    role = system_service.SysRoleService.update_role(db=db, role_id=role_id, data=data)
    return ok(role.model_dump())


@router.delete("/roles/{role_id}", response_model=None)
def delete_role(
    role_id: int,
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:role:write")),
):
    """删除角色（权限：system:role:write）。"""
    system_service.SysRoleService.delete_role(db=db, role_id=role_id)
    return ok({"deleted": True})


# ==================== 操作日志 ====================

@router.get("/operation-logs", response_model=None)
def list_operation_logs(
    db: DbSession,
    user: CurrentUser,
    _: None = Depends(require_perm("system:log:read")),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    operator: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    result: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
):
    """分页查询操作日志（权限：system:log:read）。"""
    items, total = system_service.OperationLogService.list_logs(
        db=db,
        page=page,
        page_size=page_size,
        operator=operator,
        action=action,
        result=result,
        start=start,
        end=end,
    )
    return ok(
        {
            "items": [OperationLogOut.model_validate(i).model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )