from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, Generic, ParamSpec

from common_libs.clients.rest_client import AsyncRestClient, RestClient

from ..types import RestResponse

if TYPE_CHECKING:
    from .endpoint_func import AsyncEndpointFunc, SyncEndpointFunc

P = ParamSpec("P")


class Executor(Generic[P], ABC):
    @abstractmethod
    def execute(
        self, endpoint_func: SyncEndpointFunc[P] | AsyncEndpointFunc[P], completed_path: str, params: dict[str, Any]
    ) -> RestResponse:
        raise NotImplementedError

    @abstractmethod
    def execute_stream(
        self, endpoint_func: SyncEndpointFunc[P] | AsyncEndpointFunc[P], completed_path: str, params: dict[str, Any]
    ) -> Generator[RestResponse] | AsyncGenerator[RestResponse]:
        raise NotImplementedError

    @staticmethod
    def get_rest_func(
        endpoint_func: SyncEndpointFunc[P] | AsyncEndpointFunc[P], /, *, stream: bool = False
    ) -> (
        Callable[..., RestResponse]
        | Callable[..., Generator[RestResponse]]
        | Callable[..., AsyncGenerator[RestResponse]]
    ):
        rest_client: RestClient | AsyncRestClient = endpoint_func.rest_client
        func_name = "stream" if stream else "_request"
        rest_func = partial(getattr(rest_client, func_name), endpoint_func.endpoint.method.upper())
        return rest_func


class SyncExecutor(Executor[P]):
    def execute(self, endpoint_func: SyncEndpointFunc[P], completed_path: str, params: dict[str, Any]) -> RestResponse:
        rest_func = Executor.get_rest_func(endpoint_func, stream=False)
        return rest_func(completed_path, **params)

    @contextmanager
    def execute_stream(
        self, endpoint_func: SyncEndpointFunc[P], completed_path: str, params: dict[str, Any]
    ) -> Generator[RestResponse]:
        rest_func = Executor.get_rest_func(endpoint_func, stream=True)
        with rest_func(completed_path, **params) as resp:
            yield resp


class AsyncExecutor(Executor[P]):
    async def execute(
        self, endpoint_func: AsyncEndpointFunc[P], completed_path: str, params: dict[str, Any]
    ) -> RestResponse:
        rest_func = Executor.get_rest_func(endpoint_func, stream=False)
        return await rest_func(completed_path, **params)

    @asynccontextmanager
    async def execute_stream(
        self, endpoint_func: AsyncEndpointFunc[P], completed_path: str, params: dict[str, Any]
    ) -> AsyncGenerator[RestResponse]:
        rest_func = Executor.get_rest_func(endpoint_func, stream=True)
        async with rest_func(completed_path, **params) as resp:
            yield resp
