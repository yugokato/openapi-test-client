import secrets

from fastapi import APIRouter, Depends, Request

from demo_app import _active_tokens, login_required

from .models import LoginRequest, LoginResponse, LogoutResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", status_code=201)
async def login(data: LoginRequest) -> LoginResponse:
    """Login"""
    token = secrets.token_hex(32)
    _active_tokens.add(token)
    return LoginResponse(token=token)


@router.post("/logout", dependencies=[Depends(login_required)])
async def logout(request: Request) -> LogoutResponse:
    """Logout"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
        _active_tokens.discard(token)
    return LogoutResponse(message="logged out")
