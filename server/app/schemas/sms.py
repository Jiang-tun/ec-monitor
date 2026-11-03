from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SmsProviderOut(BaseModel):
    id: int
    code: str
    name: str
    api_base: Optional[str] = None
    enabled: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SmsOrderCreate(BaseModel):
    provider_id: Optional[int] = Field(default=None, gt=0)
    platform_id: int = Field(..., gt=0)


class SmsOrderOut(BaseModel):
    id: int
    provider_id: int
    provider_code: str
    provider_order_id: Optional[str] = None
    platform_id: int
    platform_code: str
    phone: Optional[str] = None
    status: str
    sms_code: Optional[str] = None
    error: Optional[str] = None
    login_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class SmsResultIn(BaseModel):
    order_id: int = Field(..., gt=0)
    action: str = Field(..., pattern="^(acquire|fetch_code)$")
    status: str = Field(default="success", pattern="^(success|pending|failed)$")
    phone: Optional[str] = None
    code: Optional[str] = None
    code_url: Optional[str] = None
    provider_order_id: Optional[str] = None
    raw: Optional[dict] = None
    error: Optional[str] = None