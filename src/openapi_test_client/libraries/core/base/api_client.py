from __future__ import annotations

import asyncio
from typing import Any, Self

from common_libs.clients.rest_client import AsyncRestClient, RestClient
from common_libs.logging import get_logger

logger = get_logger(__name__)


class APIClient:
    """General API test client base class. All clients must inherit from this class"""

    def __init__(
        self,
        app_name: str,
        /,
        *,
        env: str | None = None,
        base_url: str | None = None,
        rest_client: RestClient | AsyncRestClient | None = None,
        async_mode: bool = False,
        raise_on_error: bool = False,
        **kwargs: Any,
    ):
        """Initialize the API client

        :param app_name: App name
        :param env: Target environment
        :param base_url: Base URL for the API
        :param rest_client: Pre-configured REST client (mutually exclusive with base_url)
        :param async_mode: Enable async mode
        :param raise_on_error: When `True`, automatically calls `raise_for_status()` on every non-2xx response,
                               raising `httpx.HTTPStatusError`.
        :param kwargs: Additional keyword arguments passed to the REST client constructor
        """
        if not async_mode:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError(
                    f"{type(self).__name__} cannot be used in sync mode inside async context. Specify async_mode=True "
                    f"to enable async mode."
                )

        self.app_name = app_name
        self.env = env
        self.async_mode = async_mode
        self.raise_on_error = raise_on_error

        if rest_client:
            if async_mode and isinstance(rest_client, RestClient):
                raise TypeError(f"rest_client must be of type {AsyncRestClient.__name__} when async_mode is True")
            if not async_mode and isinstance(rest_client, AsyncRestClient):
                raise TypeError(f"rest_client must be of type {RestClient.__name__} when async_mode is False")
            if base_url:
                raise ValueError("base_url is not supported when rest_client is provided")

            self.rest_client = rest_client
            self._base_url = rest_client.base_url
        else:
            if base_url is None:
                raise ValueError("base_url is required when rest_client is not provided")

            self._base_url = base_url
            if self.async_mode:
                self.rest_client = AsyncRestClient(self.base_url, **kwargs)
            else:
                self.rest_client = RestClient(self.base_url, **kwargs)

    def __enter__(self) -> Self:
        if self.async_mode:
            raise TypeError(f"{type(self).__name__} is in async mode. Use 'async with' instead of 'with'.")
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        if not self.async_mode:
            raise TypeError(f"{type(self).__name__} is in sync mode. Use 'with' instead of 'async with'.")
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def close(self) -> None:
        """Close the underlying HTTP client and release its connection pool.

        Safe to call multiple times. Prefer using the client as a context manager
        (`with client: ...`) when possible.
        """
        if self.async_mode:
            raise TypeError(f"{type(self).__name__} is in async mode. Use `await client.aclose()` instead.")
        self.rest_client.close()

    async def aclose(self) -> None:
        """Asynchronously close the underlying HTTP client and release its connection pool.

        Safe to call multiple times. Prefer using the client as an async context manager
        (`async with client: ...`) when possible.
        """
        if not self.async_mode:
            raise TypeError(f"{type(self).__name__} is in sync mode. Use `client.close()` instead.")
        await self.rest_client.close()

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str) -> None:
        self._base_url = url
        self.rest_client.base_url = url
