from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import CurrentUser, require_perm
from app.core.response import err, ok
from app.service import platform_auth as auth_service

router = APIRouter(prefix="/api/platform-auth", tags=["platform-auth"])


class ManualLoginIn(BaseModel):
    platform_code: str


@router.get("/cookie-status", response_model=None)
def cookie_status(
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    platform_code: str = Query(..., description="平台编码，如 jd/taobao/suning/pdd/amazon"),
):
    """检查平台登录态（Cookie）是否存在。"""
    return ok(auth_service.cookie_status(platform_code))


@router.post("/manual-login", response_model=None)
def manual_login(
    data: ManualLoginIn,
    user: CurrentUser,
    _: None = Depends(require_perm("item:write")),
):
    """启动有头浏览器供用户手动登录；成功后自动保存 Cookie 并关闭浏览器。"""
    try:
        result = auth_service.start_manual_login(data.platform_code)
        return ok(result)
    except ValueError as exc:
        return err(4001, str(exc))


@router.get("/manual-login/status", response_model=None)
def manual_login_status(
    user: CurrentUser,
    _: None = Depends(require_perm("item:read")),
    platform_code: str = Query(...),
):
    """查询手动登录进度（running/success/failed/idle）。"""
    return ok(auth_service.manual_status(platform_code))
