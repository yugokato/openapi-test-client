from __future__ import annotations

from collections.abc import Callable
from functools import update_wrapper
from threading import RLock
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from openapi_test_client.libraries.core.types import APIResponse

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

    def __init__(
        self,
        original_func: Callable[..., APIResponse],
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
        self._lock = RLock()
        self._cache: WeakKeyDictionary[APIBase[Any] | type[APIBase[Any]], dict[bool, EndpointFunc]] = (
            WeakKeyDictionary()
        )
        self.__decorators: list[EndpointDecorator] = []

    def __get__(self, instance: APIBase[Any] | None, owner: type[APIBase[Any]]) -> EndpointFunc:
        """Return an EndpointFunc object"""
        from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointFunc

        is_async = bool(instance and instance.api_client.async_mode)
        cache_key = instance or owner
        with self._lock:
            endpoint_map = self._cache.setdefault(cache_key, {})
            if not (endpoint_func := endpoint_map.get(is_async)):
                EndpointFuncClass = EndpointFunc._create(owner, self.original_func, is_async)
                endpoint_func = EndpointFuncClass(self, instance, owner)
                update_wrapper(endpoint_func, self.original_func)
                endpoint_map[is_async] = endpoint_func

            # Descriptor self-replacement optimization
            if instance is not None:
                instance.__dict__[self.original_func.__name__] = endpoint_func
        return endpoint_func

    @property
    def decorators(self) -> list[EndpointDecorator]:
        """Returns decorators that should be applied on an endpoint function"""
        return self.__decorators

    def register_decorator(self, *decorator: EndpointDecorator) -> None:
        """Register a decorator that will be applied on an endpoint function"""
        self.__decorators.extend([d for d in decorator])
