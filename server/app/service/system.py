from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import FORBIDDEN, NOT_FOUND, PARAM_INVALID, BizError
from app.core.security import hash_password
from app.db.models import SysDict, SysDictItem, SysUser
from app.dao import system as system_dao
from app.schemas.system import (
    PermissionGroupOut,
    PermissionItemOut,
    SysDictBase,
    SysDictCreate,
    SysDictUpdate,
    SysDictItemCreate,
    SysDictItemUpdate,
    SysDictItemOut,
    SysDictOut,
    SysRoleCreate,
    SysRoleOut,
    SysRoleUpdate,
    SysUserCreate,
    SysUserOut,
    SysUserUpdate,
)


# ==================== 字典类型服务层 ====================

class SysDictService:
    @staticmethod
    def list_dicts(db: Session, page: int = 1, page_size: int = 20, keyword: Optional[str] = None) -> Tuple[List[SysDict], int]:
        return system_dao.list_dicts(db=db, page=page, page_size=page_size, keyword=keyword)

    @staticmethod
    def get_dict_by_code(db: Session, code: str) -> Optional[SysDict]:
        return system_dao.get_dict_by_code(db, code)

    @staticmethod
    def create_dict(db: Session, data: SysDictCreate) -> SysDict:
        obj = SysDict(**data.model_dump())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @staticmethod
    def update_dict(db: Session, dict_code: str, data: SysDictUpdate) -> Optional[SysDict]:
        item = system_dao.get_dict_by_code(db, dict_code)
        if not item:
            return None
        update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        for k, v in update_data.items():
            setattr(item, k, v)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete_dict(db: Session, dict_code: str) -> bool:
        item = system_dao.get_dict_by_code(db, dict_code)
        if not item:
            return False
        system_dao.delete_dict(db=db, dict_code=dict_code)
        return True


# ==================== 字典项服务层 ====================

class SysDictItemService:
    @staticmethod
    def list_dict_items(db: Session, dict_code: str, page: int = 1, page_size: int = 20, status: Optional[int] = None, keyword: Optional[str] = None) -> Tuple[List[SysDictItem], int]:
        return system_dao.list_dict_items(db=db, dict_code=dict_code, page=page, page_size=page_size, status=status, keyword=keyword)

    @staticmethod
    def get_dict_item(db: Session, item_id: int) -> Optional[SysDictItem]:
        return system_dao.get_dict_item(db, item_id)

    @staticmethod
    def create_dict_item(db: Session, data: SysDictItemCreate, dict_code: Optional[str] = None) -> SysDictItem:
        payload = data.model_dump()
        if dict_code:
            payload["dict_code"] = dict_code
        obj = SysDictItem(**payload)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @staticmethod
    def update_dict_item(db: Session, item_id: int, data: SysDictItemUpdate) -> Optional[SysDictItem]:
        item = system_dao.get_dict_item(db, item_id)
        if not item:
            return None
        update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        for k, v in update_data.items():
            setattr(item, k, v)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete_dict_item(db: Session, item_id: int) -> bool:
        item = system_dao.get_dict_item(db, item_id)
        if not item:
            return False
        item.is_deleted = 1
        db.commit()
        return True


# ==================== 全局单例 ====================

dict_service = SysDictService()
dict_item_service = SysDictItemService()

# 兼容 API 层调用的函数式入口
list_dicts = dict_service.list_dicts
create_dict = dict_service.create_dict
update_dict = dict_service.update_dict
delete_dict = dict_service.delete_dict

list_dict_items = dict_item_service.list_dict_items
create_dict_item = dict_item_service.create_dict_item
update_dict_item = dict_item_service.update_dict_item
delete_dict_item = dict_item_service.delete_dict_item


# ==================== 权限点目录 ====================

PERMISSION_GROUPS: List[dict] = [
    {
        "group": "数据概览",
        "items": [{"code": "dashboard:read", "name": "查看看板"}],
    },
    {
        "group": "商品管理",
        "items": [
            {"code": "item:read", "name": "查看商品"},
            {"code": "item:write", "name": "编辑商品"},
            {"code": "item:import", "name": "批量导入"},
        ],
    },
    {
        "group": "监控告警",
        "items": [
            {"code": "alert:read", "name": "查看告警"},
            {"code": "alert:confirm", "name": "确认告警"},
            {"code": "alert:rule", "name": "告警规则配置"},
        ],
    },
    {
        "group": "质量管理",
        "items": [
            {"code": "quality:read", "name": "查看异常"},
            {"code": "quality:write", "name": "登记异常"},
            {"code": "quality:review", "name": "复核异常"},
        ],
    },
    {
        "group": "代理池",
        "items": [
            {"code": "proxy:read", "name": "查看代理"},
            {"code": "proxy:write", "name": "维护代理"},
        ],
    },
    {
        "group": "死信队列",
        "items": [{"code": "retry:manual", "name": "手工重试"}],
    },
    {
        "group": "系统配置",
        "items": [
            {"code": "system:dict:read", "name": "查看字典"},
            {"code": "system:dict:write", "name": "维护字典"},
        ],
    },
    {
        "group": "系统管理",
        "items": [
            {"code": "system:user:read", "name": "查看用户"},
            {"code": "system:user:write", "name": "维护用户"},
            {"code": "system:role:read", "name": "查看角色"},
            {"code": "system:role:write", "name": "维护角色"},
            {"code": "system:log:read", "name": "查看操作日志"},
        ],
    },
    {
        "group": "采集与报表",
        "items": [
            {"code": "node:manage", "name": "节点管理"},
            {"code": "report:read", "name": "查看报表"},
            {"code": "report:write", "name": "生成报表"},
        ],
    },
]

ALL_PERMISSIONS: List[str] = [
    item["code"] for g in PERMISSION_GROUPS for item in g["items"]
]


def list_permission_groups() -> List[PermissionGroupOut]:
    return [
        PermissionGroupOut(
            group=g["group"],
            items=[PermissionItemOut(**i) for i in g["items"]],
        )
        for g in PERMISSION_GROUPS
    ]


# ==================== 用户管理服务 ====================

class SysUserService:
    @staticmethod
    def _to_out(db: Session, user: SysUser) -> SysUserOut:
        role_ids = system_dao.get_user_role_ids(db, user.id)
        roles = []
        for rid in role_ids:
            role = system_dao.get_role(db, rid)
            if role:
                roles.append(role.role_code)
        out = SysUserOut.model_validate(user)
        out.role_ids = role_ids
        out.roles = roles
        return out

    @staticmethod
    def list_users(
        db: Session,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[int] = None,
    ) -> Tuple[List[SysUserOut], int]:
        rows, total = system_dao.list_users(
            db, page=page, page_size=page_size, keyword=keyword, status=status
        )
        return [SysUserService._to_out(db, u) for u in rows], total

    @staticmethod
    def get_user(db: Session, user_id: int) -> SysUserOut:
        user = system_dao.get_user(db, user_id)
        if not user:
            raise BizError(NOT_FOUND, "用户不存在")
        return SysUserService._to_out(db, user)

    @staticmethod
    def create_user(db: Session, data: SysUserCreate) -> SysUserOut:
        if system_dao.get_user_by_username(db, data.username):
            raise BizError(PARAM_INVALID, "用户名已存在")
        payload = data.model_dump(exclude={"password", "role_ids"})
        user = system_dao.create_user(
            db, **payload, password_hash=hash_password(data.password)
        )
        db.commit()
        system_dao.set_user_roles(db, user.id, data.role_ids)
        db.refresh(user)
        return SysUserService._to_out(db, user)

    @staticmethod
    def update_user(db: Session, user_id: int, data: SysUserUpdate) -> SysUserOut:
        user = system_dao.get_user(db, user_id)
        if not user:
            raise BizError(NOT_FOUND, "用户不存在")
        fields = data.model_dump(exclude_unset=True, exclude={"role_ids"})
        for k, v in fields.items():
            setattr(user, k, v)
        db.commit()
        if data.role_ids is not None:
            system_dao.set_user_roles(db, user_id, data.role_ids)
        db.refresh(user)
        return SysUserService._to_out(db, user)

    @staticmethod
    def delete_user(db: Session, user_id: int, current_user_id: int) -> None:
        user = system_dao.get_user(db, user_id)
        if not user:
            raise BizError(NOT_FOUND, "用户不存在")
        if user.id == current_user_id:
            raise BizError(FORBIDDEN, "不能删除当前登录用户")
        if user.username == "admin":
            raise BizError(FORBIDDEN, "内置管理员不可删除")
        system_dao.delete_user(db, user)

    @staticmethod
    def reset_password(db: Session, user_id: int, password: str) -> None:
        user = system_dao.get_user(db, user_id)
        if not user:
            raise BizError(NOT_FOUND, "用户不存在")
        user.password_hash = hash_password(password)
        db.commit()


# ==================== 角色管理服务 ====================

class SysRoleService:
    @staticmethod
    def _to_out(role, user_count: int = 0) -> SysRoleOut:
        out = SysRoleOut.model_validate(role)
        out.permissions = role.permissions or []
        out.user_count = user_count
        return out

    @staticmethod
    def list_roles(db: Session, keyword: Optional[str] = None) -> List[SysRoleOut]:
        rows = system_dao.list_roles(db, keyword=keyword)
        counts = system_dao.count_role_users(db)
        return [SysRoleService._to_out(r, counts.get(r.id, 0)) for r in rows]

    @staticmethod
    def create_role(db: Session, data: SysRoleCreate) -> SysRoleOut:
        if system_dao.get_role_by_code(db, data.role_code):
            raise BizError(PARAM_INVALID, "角色编码已存在")
        perms = [p for p in dict.fromkeys(data.permissions) if p in ALL_PERMISSIONS]
        role = system_dao.create_role(
            db,
            role_code=data.role_code,
            role_name=data.role_name,
            permissions=perms,
        )
        return SysRoleService._to_out(role, 0)

    @staticmethod
    def update_role(db: Session, role_id: int, data: SysRoleUpdate) -> SysRoleOut:
        role = system_dao.get_role(db, role_id)
        if not role:
            raise BizError(NOT_FOUND, "角色不存在")
        if data.role_name is not None:
            role.role_name = data.role_name
        if data.permissions is not None:
            role.permissions = [
                p for p in dict.fromkeys(data.permissions) if p in ALL_PERMISSIONS
            ]
        db.commit()
        db.refresh(role)
        counts = system_dao.count_role_users(db)
        return SysRoleService._to_out(role, counts.get(role.id, 0))

    @staticmethod
    def delete_role(db: Session, role_id: int) -> None:
        role = system_dao.get_role(db, role_id)
        if not role:
            raise BizError(NOT_FOUND, "角色不存在")
        if role.role_code == "admin":
            raise BizError(FORBIDDEN, "内置管理员角色不可删除")
        system_dao.delete_role(db, role)


# ==================== 操作日志服务 ====================

class OperationLogService:
    @staticmethod
    def list_logs(
        db: Session,
        page: int = 1,
        page_size: int = 20,
        operator: Optional[str] = None,
        action: Optional[str] = None,
        result: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        return system_dao.list_operation_logs(
            db,
            page=page,
            page_size=page_size,
            operator=operator,
            action=action,
            result=result,
            start=start,
            end=end,
        )