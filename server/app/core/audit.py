import json
import logging

import jwt as pyjwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import TOKEN_TYPE_ACCESS, decode_token
from app.db.models import OperationLog
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PREFIXES = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/internal",
    "/docs",
    "/openapi.json",
)
_VERB = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def _operator(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return "anonymous"
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, TOKEN_TYPE_ACCESS)
        return payload.get("sub") or "anonymous"
    except pyjwt.InvalidTokenError:
        return "anonymous"
    except Exception:
        return "anonymous"


def _target(request: Request) -> tuple[str, str | None]:
    path = request.url.path
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        parts = parts[1:]
    if not parts:
        return "unknown", None
    resource = parts[0].replace("-", "_")
    if resource == "system" and len(parts) > 1 and not parts[1].isdigit():
        resource = f"system.{parts[1].replace('-', '_')}"
    target_id = parts[-1] if parts[-1].isdigit() else None
    return resource, target_id


def _write_log(
    operator: str,
    action: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    result: str,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            OperationLog(
                operator=operator,
                action=action,
                target_type=target_type,
                target_id=target_id,
                ip=request.client.host if request.client else None,
                trace_id=getattr(request.state, "trace_id", None),
                result=result,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 审计失败不能影响业务
        db.rollback()
        logger.exception("write operation log failed")
    finally:
        db.close()


class AuditMiddleware(BaseHTTPMiddleware):
    """记录所有写操作的审计日志（自动推断资源与动作）。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in _MUTATING or request.url.path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)

        body = b""
        if hasattr(response, "body_iterator"):
            async for chunk in response.body_iterator:
                body += chunk
            response = Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        result = "success"
        if response.status_code >= 400:
            result = "failed"
        else:
            try:
                payload = json.loads(body) if body else {}
                if isinstance(payload, dict) and payload.get("code") not in (0, None):
                    result = "failed"
            except (ValueError, TypeError):
                pass

        resource, target_id = _target(request)
        _write_log(
            operator=_operator(request),
            action=f"{resource}.{_VERB.get(request.method, request.method.lower())}",
            target_type=resource,
            target_id=target_id,
            request=request,
            result=result,
        )
        return response
