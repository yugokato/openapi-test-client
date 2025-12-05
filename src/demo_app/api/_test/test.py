import asyncio

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

router = APIRouter(prefix="/test", tags=["Test"])


@router.get("/echo/{value}", status_code=200)
async def echo(value: str) -> int | str:
    """Test endpoint that just echos the specified value"""
    return int(value) if value.isdigit() else value


@router.get("/wait/{delay}", status_code=200)
async def wait(delay: int | float) -> str:
    """Test endpoint that returns a response after waiting for the specified delay"""
    await asyncio.sleep(delay)
    return "ok"


@router.get("/redirect")
async def redirect(request: Request) -> RedirectResponse:
    """Test endpoint that redirects to /redirected"""
    return RedirectResponse(request.url_for("redirected"), status_code=301)


@router.get("/redirected", status_code=200)
async def redirected() -> str:
    """Test endpoint for the redirected route"""
    return "ok"
