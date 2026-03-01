from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import ApiMeta


class SessionUserData(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_active: bool

    model_config = ConfigDict(extra="forbid")


class AuthMeData(BaseModel):
    authenticated: bool
    csrf_token: str
    user: SessionUserData

    model_config = ConfigDict(extra="forbid")


class AuthMeEnvelope(BaseModel):
    data: AuthMeData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class CsrfBootstrapData(BaseModel):
    csrf_token: str
    authenticated: bool

    model_config = ConfigDict(extra="forbid")


class CsrfBootstrapEnvelope(BaseModel):
    data: CsrfBootstrapData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    model_config = ConfigDict(extra="forbid")


class LoginData(BaseModel):
    authenticated: bool
    csrf_token: str
    user: SessionUserData

    model_config = ConfigDict(extra="forbid")


class LoginEnvelope(BaseModel):
    data: LoginData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)

    model_config = ConfigDict(extra="forbid")
