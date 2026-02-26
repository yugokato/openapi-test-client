from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar, cast

from common_libs.clients.rest_client import RestResponse

if TYPE_CHECKING:
    from openapi_test_client.libraries.core.api_classes import APIBase
    from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointDecorator, EndpointFunc

__all__ = ["EndpointHandler"]


class EndpointHandler:
    """A class to encapsulate each API class function (original function) inside a dynamically generated
    EndpointFunc class

    An instance of EndpointHandler class works like a proxy to an EndpointFunc object when an API class function is
    called, which makes the original API function to behave as an EndpointFunc class object instead.
    Each EndpointFunc class will be named in the format of: <APIClassName><APIFunctionName>EndpointFunc

    eg: Accessing <class AuthAPI>.login will return AuthAPILoginEndpointFunc class object
    """

    # cache endpoint function objects
    _endpoint_functions: ClassVar[dict[tuple[str, APIBase | None, type[APIBase]], EndpointFunc]] = {}
    _lock = RLock()

    def __init__(
        self,
        original_func: Callable[..., RestResponse],
        method: str,
        path: str,
        use_query_string: bool = False,
        **default_raw_options: Any,
    ) -> None:
        self.original_func = original_func
        self.method = method
        self.path = path
        self.use_query_string = use_query_string
        self.default_raw_options = default_raw_options

        # Will be set via @endpoint.<decorator_name>
        self.content_type: str | None = None  # application/json by default
        self.is_public = False
        self.is_documented = True
        self.is_deprecated = False
        self.__decorators: list[EndpointDecorator] = []

    def __get__(self, instance: APIBase | None, owner: type[APIBase]) -> EndpointFunc:
        """Return an EndpointFunc object"""
        from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointFunc

        key = (self.original_func.__name__, instance, owner)
        is_async = bool(instance and instance.api_client.async_mode)
        from functools import update_wrapper

        with EndpointHandler._lock:
            if not (endpoint_func := EndpointHandler._endpoint_functions.get(key)):
                EndpointFuncClass = EndpointFunc._create(owner, self.original_func, is_async)
                endpoint_func = EndpointFuncClass(self, instance, owner)
                EndpointHandler._endpoint_functions[key] = cast(
                    EndpointFunc, update_wrapper(endpoint_func, self.original_func)
                )
        return endpoint_func

    @property
    def decorators(self) -> list[EndpointDecorator]:
        """Returns decorators that should be applied on an endpoint function"""
        return self.__decorators

    def register_decorator(self, *decorator: EndpointDecorator) -> None:
        """Register a decorator that will be applied on an endpoint function"""
        self.__decorators.extend([d for d in decorator])
