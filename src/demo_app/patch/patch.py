import inspect
from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRouter as _APIRouter

__all__ = ("APIRouter",)


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
