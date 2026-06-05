"""OpenAPI-aware API base class with built-in Pydantic validation support."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, contextmanager, nullcontext
from functools import wraps
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

import openapi_test_client.libraries.openapi.utils.pydantic_model as pydantic_model_util
from openapi_test_client.libraries.core.base.api_class import APIBase
from openapi_test_client.libraries.openapi.endpoints import Endpoint
from openapi_test_client.libraries.openapi.endpoints.endpoint_func import AsyncEndpointFunc, SyncEndpointFunc
from openapi_test_client.libraries.openapi.json_encoder import CustomJsonEncoder
from openapi_test_client.libraries.openapi.types import ENDPOINT_FUNC_CONTROL_KWARGS, File, MultipartFormData
from openapi_test_client.libraries.openapi.validation import OpenAPIRequestValidator

if TYPE_CHECKING:
    from openapi_test_client.libraries.openapi.base.api_client import OpenAPIClient

T = TypeVar("T", bound="OpenAPIClient")


class OpenAPIBase(APIBase[T]):
    """OpenAPI-aware API base class with built-in Pydantic validation support.

    When validation mode is active (VALIDATION_MODE env var is set, or validate=True is passed to
    an API call), each endpoint call will automatically validate request parameters against the
    endpoint model using Pydantic in strict mode.
    """

    TAGs: ClassVar[tuple[str, ...]]
    _endpoint_class: ClassVar[type[Endpoint[Any]]] = Endpoint
    _sync_endpoint_func_class: ClassVar[type[SyncEndpointFunc[Any]]] = SyncEndpointFunc
    _async_endpoint_func_class: ClassVar[type[AsyncEndpointFunc[Any]]] = AsyncEndpointFunc

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "TAGs" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} must define class attribute TAGs")
        if not isinstance(cls.TAGs, tuple):
            raise TypeError("TAGs must be a tuple of strings")

    def pre_request_hook(self, endpoint: Endpoint[Any], *args: Any, **params: Any) -> None:
        """Invoke Pydantic validation in strict mode when validation mode is active.

        :param endpoint: Endpoint object associated with an endpoint function called
        :param args: API path parameters
        :param params: API parameters sent with the request
        """
        super().pre_request_hook(endpoint, *args, **params)
        if pydantic_model_util.is_validation_mode():
            OpenAPIRequestValidator().validate(endpoint, args, params)

    def request_wrapper(self) -> list[Callable[..., Any]]:
        """Return wrappers that handle validate= kwarg and normalize params in validation mode.

        - validation_handler (outermost): pops validate= kwarg; overrides validation mode for this
          call when validate is not None (True forces on; False forces off).
        - validation_normalizer (inner): JSON-roundtrips body/query params when in validation mode so that
          PydanticModel instances returned by ParamModel.__new__ are serialized to plain dicts before the
          HTTP request is sent.
        """

        def validation_handler(call: Callable[..., Any]) -> Callable[..., Any]:
            if inspect.iscoroutinefunction(call):

                @wraps(call)
                async def async_validation_handler(endpoint_func: Any, *args: Any, **kwargs: Any) -> Any:
                    validate = kwargs.pop("validate", None)
                    with pydantic_model_util.in_validation_mode(validate) if validate is not None else nullcontext():
                        return await call(endpoint_func, *args, **kwargs)

                return async_validation_handler
            else:

                @wraps(call)
                def sync_validation_handler(endpoint_func: Any, *args: Any, **kwargs: Any) -> Any:
                    validate = kwargs.pop("validate", None)
                    with pydantic_model_util.in_validation_mode(validate) if validate is not None else nullcontext():
                        return call(endpoint_func, *args, **kwargs)

                return sync_validation_handler

        def validation_normalizer(call: Callable[..., Any]) -> Callable[..., Any]:
            if inspect.iscoroutinefunction(getattr(call, "__wrapped__", call)):

                @wraps(call)
                async def async_validation_normalizer(endpoint_func: Any, *args: Any, **kwargs: Any) -> Any:
                    if pydantic_model_util.is_validation_mode():
                        control_kwargs = {k: v for k, v in kwargs.items() if k in ENDPOINT_FUNC_CONTROL_KWARGS}
                        body_or_query_params = {
                            k: v for k, v in kwargs.items() if k not in ENDPOINT_FUNC_CONTROL_KWARGS
                        }
                        kwargs = {**control_kwargs, **_serialize_params(body_or_query_params)}
                    return await call(endpoint_func, *args, **kwargs)

                return async_validation_normalizer
            else:

                @wraps(call)
                def sync_validation_normalizer(endpoint_func: Any, *args: Any, **kwargs: Any) -> Any:
                    if pydantic_model_util.is_validation_mode():
                        control_kwargs = {k: v for k, v in kwargs.items() if k in ENDPOINT_FUNC_CONTROL_KWARGS}
                        body_or_query_params = {
                            k: v for k, v in kwargs.items() if k not in ENDPOINT_FUNC_CONTROL_KWARGS
                        }
                        kwargs = {**control_kwargs, **_serialize_params(body_or_query_params)}
                    return call(endpoint_func, *args, **kwargs)

                return sync_validation_normalizer

        return [validation_handler, *super().request_wrapper(), validation_normalizer]

    def stream_wrapper(self) -> list[Callable[..., Any]]:
        """Return a wrapper that handles validate= kwarg for streaming calls.

        Activates in_validation_mode() inside the contextmanager body (where the actual HTTP request
        is sent), not around the call that returns the contextmanager, so the env var remains set
        during pre_request_hook execution.

        Dispatches on whether the underlying stream method is async (AsyncEndpointFunc.stream) or
        sync (SyncEndpointFunc.stream).
        """

        def stream_validation_handler(call: Callable[..., Any]) -> Callable[..., Any]:
            original = inspect.unwrap(call)
            if inspect.isasyncgenfunction(original):

                @wraps(call)
                @asynccontextmanager
                async def async_wrapper(endpoint_func: Any, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
                    validate = kwargs.pop("validate", None)
                    with pydantic_model_util.in_validation_mode(validate) if validate is not None else nullcontext():
                        async with call(endpoint_func, *args, **kwargs) as resp:
                            yield resp

                return async_wrapper
            else:

                @wraps(call)
                @contextmanager
                def sync_wrapper(endpoint_func: Any, *args: Any, **kwargs: Any) -> Generator[Any, None, None]:
                    validate = kwargs.pop("validate", None)
                    with pydantic_model_util.in_validation_mode(validate) if validate is not None else nullcontext():
                        with call(endpoint_func, *args, **kwargs) as resp:
                            yield resp

                return sync_wrapper

        return [stream_validation_handler, *super().stream_wrapper()]


def _serialize_params(params: dict[str, Any]) -> dict[str, Any]:
    """JSON-normalize parameter values while preserving upload/binary payload types.

    File/MultipartFormData/bytes values must not be JSON-roundtripped: bytes are not JSON-serializable as-is, and File
    is a dict subclass that would be reduced to a plain dict, breaking the isinstance(v, File) file-routing check
    downstream.
    """
    return {
        k: v if isinstance(v, (File, MultipartFormData, bytes)) else json.loads(json.dumps(v, cls=CustomJsonEncoder))
        for k, v in params.items()
    }
