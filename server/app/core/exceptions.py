"""统一业务异常与错误码（详见设计报告 4.1.3）。"""
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# ---- 错误码常量 ----
OK = 0
PARAM_MISSING = 1001
PARAM_INVALID = 1002
IDEMPOTENCY_CONFLICT = 1003

UNAUTHORIZED = 3001
FORBIDDEN = 3003
TOKEN_EXPIRED = 3004

NOT_FOUND = 4004
RESOURCE_DISABLED = 4009

INTERNAL_ERROR = 5001
DEPENDENCY_TIMEOUT = 5002


class BizError(Exception):
    """业务异常：携带错误码，由全局 handler 渲染为统一响应体。"""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


def _body(code: int, message: str, request: Request, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data, "trace_id": _trace_id(request)}


# HTTP 状态码 → 业务错误码映射（未显式指定 code 的 HTTPException 用此表）
_STATUS_MAP = {
    400: PARAM_INVALID,
    401: UNAUTHORIZED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    409: IDEMPOTENCY_CONFLICT,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz(request: Request, exc: BizError):
        status = 200 if exc.code == OK else _biz_status(exc.code)
        return JSONResponse(status_code=status, content=_body(exc.code, exc.message, request, exc.data))

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        code = getattr(exc, "status_code", 500)
        biz_code = _STATUS_MAP.get(code, INTERNAL_ERROR if code >= 500 else PARAM_INVALID)
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=_biz_status(biz_code), content=_body(biz_code, detail, request))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        msg = f"{loc}: {first.get('msg', '参数校验失败')}"
        return JSONResponse(status_code=200, content=_body(PARAM_INVALID, msg, request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return JSONResponse(
            status_code=200,
            content=_body(INTERNAL_ERROR, f"内部错误: {type(exc).__name__}", request),
        )


def _biz_status(code: int) -> int:
    """业务错误码 → HTTP 状态码。本系统约定：业务失败统一 HTTP 200，用 code 区分；
    仅未认证/无权限返回对应 4xx（方便网关/前端拦截）。"""
    if code == UNAUTHORIZED:
        return 401
    if code == FORBIDDEN:
        return 403
    if code == NOT_FOUND:
        return 404
    return 200
