from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: Optional[T] = None
    trace_id: Optional[str] = None


class PageData(BaseModel, Generic[T]):
    items: list[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class PageResp(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: PageData[T]


def ok(data: Any = None, trace_id: Optional[str] = None) -> dict:
    return {"code": 0, "message": "success", "data": data, "trace_id": trace_id}


def err(code: int, message: str, trace_id: Optional[str] = None) -> dict:
    return {"code": code, "message": message, "data": None, "trace_id": trace_id}
