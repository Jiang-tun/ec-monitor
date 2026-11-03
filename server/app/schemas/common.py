from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LoginReq(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=64)


class RefreshReq(BaseModel):
    refresh_token: str = Field(min_length=20)


class ChangePasswordReq(BaseModel):
    old_password: str = Field(min_length=6, max_length=64)
    new_password: str = Field(min_length=8, max_length=64)
