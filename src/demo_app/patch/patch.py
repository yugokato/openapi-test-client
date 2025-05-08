import inspect
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.routing import APIRouter as _APIRouter
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer as _HTTPBearer

__all__ = ("APIRouter", "HTTPBearer")


class APIRouter(_APIRouter):
    """Patched APIRouter for https://github.com/fastapi/fastapi/discussions/7504"""

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        summary: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> None:
        if summary is None and endpoint.__doc__:
            summary = inspect.cleandoc(endpoint.__doc__.strip().splitlines()[0])
        if description is None and endpoint.__doc__:
            description = inspect.cleandoc(
                "\n".join(endpoint.__doc__.strip().splitlines()[1:]),
            )
        super().add_api_route(
            path,
            endpoint,
            summary=summary,
            description=description,
            **kwargs,
        )


class HTTPBearer(_HTTPBearer):
    """Patched HTTPBearer for https://github.com/fastapi/fastapi/issues/2026 and
    https://github.com/fastapi/fastapi/discussions/9130"""

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials:
        try:
            return await super().__call__(request)
        except HTTPException as exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exception.detail)
