from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any

from common_libs.clients.rest_client import APIResponse, RestClient, RestResponse

if TYPE_CHECKING:
    from .endpoint_func import AsyncEndpointFunc, SyncEndpointFunc


class Executor(ABC):
    @abstractmethod
    def execute(
        self, endpoint_func: SyncEndpointFunc | AsyncEndpointFunc, completed_path: str, params: dict[str, Any]
    ) -> RestResponse:
        raise NotImplementedError

    @abstractmethod
    def execute_stream(
        self, endpoint_func: SyncEndpointFunc | AsyncEndpointFunc, completed_path: str, params: dict[str, Any]
    ) -> Generator[RestResponse] | AsyncGenerator[RestResponse]:
        raise NotImplementedError

    @staticmethod
    def get_rest_func(
        endpoint_func: SyncEndpointFunc | AsyncEndpointFunc, /, *, stream: bool = False
    ) -> (
        Callable[..., APIResponse]
        | Callable[..., Generator[RestResponse]]
        | Callable[..., AsyncGenerator[RestResponse]]
    ):
        rest_client: RestClient = endpoint_func.rest_client
        if stream:
            rest_func = partial(getattr(rest_client, "stream"), endpoint_func.endpoint.method.upper())
        else:
            rest_func = getattr(rest_client, f"_{endpoint_func.method}")
        return rest_func


class SyncExecutor(Executor):
    def execute(self, endpoint_func: SyncEndpointFunc, completed_path: str, params: dict[str, Any]) -> RestResponse:
        rest_func = SyncExecutor.get_rest_func(endpoint_func, stream=False)
        return rest_func(completed_path, **params)

    @contextmanager
    def execute_stream(
        self, endpoint_func: SyncEndpointFunc, completed_path: str, params: dict[str, Any]
    ) -> Generator[RestResponse]:
        rest_func = SyncExecutor.get_rest_func(endpoint_func, stream=True)
        with rest_func(completed_path, **params) as resp:
            yield resp


class AsyncExecutor(Executor):
    async def execute(
        self, endpoint_func: AsyncEndpointFunc, completed_path: str, params: dict[str, Any]
    ) -> RestResponse:
        rest_func = SyncExecutor.get_rest_func(endpoint_func, stream=False)
        return await rest_func(completed_path, **params)

    @asynccontextmanager
    async def execute_stream(
        self, endpoint_func: AsyncEndpointFunc, completed_path: str, params: dict[str, Any]
    ) -> AsyncGenerator[RestResponse]:
        rest_func = SyncExecutor.get_rest_func(endpoint_func, stream=True)
        async with rest_func(completed_path, **params) as resp:
            yield resp
