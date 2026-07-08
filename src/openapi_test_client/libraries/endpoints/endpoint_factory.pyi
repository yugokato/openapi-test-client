from collections.abc import Callable
from typing import Any, Concatenate, ParamSpec, TypeAlias, TypeVar, overload

from api_client_core.endpoints.endpoint_factory import endpoint as _endpoint
from api_client_core.endpoints.endpoint_handler import PendingOperations
from api_client_core.types import RestResponse

from openapi_test_client.libraries.base import OpenAPIBase
from openapi_test_client.libraries.endpoints.endpoint_handler import EndpointHandler

__all__ = ["endpoint"]

T = TypeVar("T", bound=OpenAPIBase[Any])
P = ParamSpec("P")
R = TypeVar("R", bound=RestResponse)

_OrigFunc: TypeAlias = Callable[Concatenate[T, P], R]
_HandlerOrPending: TypeAlias = EndpointHandler[P] | PendingOperations[P]
_OrigFuncOrPending: TypeAlias = _OrigFunc[T, P, R] | PendingOperations[P]

class endpoint(_endpoint):
    """Narrowed-type stub for `endpoint`.

    See the api-client-core `endpoint` class for behavior.
    """

    @staticmethod
    def get(path: str, **default_raw_options: Any) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def post(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def delete(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def put(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def patch(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def options(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def head(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @staticmethod
    def trace(
        path: str, use_query_string: bool = ..., **default_raw_options: Any
    ) -> Callable[[_OrigFunc[T, P, R]], EndpointHandler[P]]: ...
    @overload
    @staticmethod
    def undocumented(obj: type[T]) -> type[T]: ...
    @overload
    @staticmethod
    def undocumented(obj: EndpointHandler[P]) -> EndpointHandler[P]: ...
    @overload
    @staticmethod
    def undocumented(obj: _OrigFuncOrPending[T, P, R]) -> PendingOperations[P]: ...
    @overload
    @staticmethod
    def is_public(obj: EndpointHandler[P]) -> EndpointHandler[P]: ...
    @overload
    @staticmethod
    def is_public(obj: _OrigFuncOrPending[T, P, R]) -> PendingOperations[P]: ...
    @overload
    @staticmethod
    def is_deprecated(obj: type[T]) -> type[T]: ...
    @overload
    @staticmethod
    def is_deprecated(obj: EndpointHandler[P]) -> EndpointHandler[P]: ...
    @overload
    @staticmethod
    def is_deprecated(obj: _OrigFuncOrPending[T, P, R]) -> PendingOperations[P]: ...
    @staticmethod
    def content_type(content_type: str) -> Callable[[_HandlerOrPending[P]], _HandlerOrPending[P]]: ...
