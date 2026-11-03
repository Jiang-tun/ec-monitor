import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TraceMiddleware(BaseHTTPMiddleware):
    """为每个请求生成/透传 trace_id，并记录耗时（详见 4.1.2 统一响应体）。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        tid = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        request.state.trace_id = tid
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        response.headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - start) * 1000:.1f}"
        return response
