import secrets

from fastapi import APIRouter

from .models import LoginRequest, LoginResponse, LogoutResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", status_code=201)
async def login(data: LoginRequest) -> LoginResponse:
    """Login"""
    # Just return a random value as there's no actual BE
    return LoginResponse(token=secrets.token_hex(32))


@router.post("/logout")
async def logout() -> LogoutResponse:
    """Logout"""
    return LogoutResponse(message="logged out")
