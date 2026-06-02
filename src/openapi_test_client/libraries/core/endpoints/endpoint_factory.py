from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from ..types import RestResponse
from .endpoint_handler import (
    DeferredOperation,
    EndpointHandler,
    PendingHandler,
)

if TYPE_CHECKING:
    from ..base import APIBase


T = TypeVar("T", bound="APIBase[Any]")
P = ParamSpec("P")
R = TypeVar("R", bound=RestResponse)

__all__ = ["endpoint"]


class endpoint:
    """An endpoint factory that converts a wrapped API class function to an EndpointHandler instance that returns a
    dynamically-created EndpointFunc instance when accessed

    An EndpointFunc instance can be accessed by the following two ways:
    - class-level:    <API Class>.<API class function>
    - instance-level: <API Class instance>.<API class function>

    Example:
        >>> from typing import Unpack
        >>>
        >>> from myproject.clients.my_app.my_app_client import MyAppAPIClient
        >>> from myproject.clients.my_app.api.base.my_app_api import MyAppBaseAPI
        >>> from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointFunc
        >>> from openapi_test_client.libraries.core.types import Kwargs, Unset
        >>>
        >>> class AuthAPI(MyAppBaseAPI):
        >>>     @endpoint.post("/v1/login")
        >>>     def login(
        >>>         self, *, username: str = Unset, password: str = Unset, **kwargs: Unpack[Kwargs]
        >>>     ) -> RestResponse:
        >>>         ...
        >>>
        >>> client = MyAppAPIClient()
        >>> type(client.Auth.login)
        <class 'openapi_test_client.libraries.core.endpoints.endpoint_func.AuthAPILoginEndpointFunc'>
        >>> type(AuthAPI.login)
        <class 'openapi_test_client.libraries.core.endpoints.endpoint_func.AuthAPILoginEndpointFunc'>
        >>> from openapi_test_client.libraries.core import EndpointFunc
        >>> isinstance(client.Auth.login, EndpointFunc) and isinstance(AuthAPI.login, EndpointFunc)
        True
        >>> client.Auth.login.endpoint
        Endpoint(api_class=<class 'myproject.clients.my_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url='https://api.my-app.com/v1/auth/login', content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> AuthAPI.login.endpoint
        Endpoint(api_class=<class 'myproject.clients.my_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url=None, content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> str(client.Auth.login.endpoint)
        'POST /v1/auth/login'
        >>> str(AuthAPI.login.endpoint)
        'POST /v1/auth/login'
        >>> client.Auth.login.endpoint.path
        '/v1/auth/login'
        >>> client.Auth.login.endpoint.url
        'https://api.my-app.com/v1/auth/login'

    """  # noqa: E501

    @staticmethod
    def get(path: str, **default_raw_options: Any) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for a GET API function

        :param path: The endpoint path
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("get", path, use_query_string=True, **default_raw_options)

    @staticmethod
    def post(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for a POST API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("post", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def delete(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for a DELETE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("delete", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def put(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for a PUT API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("put", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def patch(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for a PATCH API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the httpx
        """
        return endpoint._create("patch", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def options(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for an OPTIONS API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("options", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def head(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for an HEAD API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("head", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def trace(
        path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns a decorator that generates an endpoint handler for an TRACE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("trace", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def undocumented(obj: EndpointHandler[P] | type[T]) -> EndpointHandler[P] | type[T]:
        """Mark an endpoint as undocumented. If an API class is decorated, all endpoints on the class will be
        automatically marked as undocumented.
        The flag value is available with an Endpoint object's is_documented attribute

        :param obj: Endpoint handler, API class, or API function
        """
        from ..base import APIBase

        if inspect.isclass(obj) and issubclass(obj, APIBase):
            obj.is_documented = False
            return obj
        return endpoint._apply_operations(obj, lambda h: setattr(h, "is_documented", False))

    @staticmethod
    def is_public(obj: EndpointHandler[P]) -> EndpointHandler[P]:
        """Mark an endpoint as a public API that does not require authentication.
        The flag value is available with an Endpoint object's is_public attribute

        :param obj: Endpoint handler or API function
        """
        return endpoint._apply_operations(obj, lambda h: setattr(h, "is_public", True))

    @staticmethod
    def is_deprecated(obj: EndpointHandler[P] | type[T]) -> EndpointHandler[P] | type[T]:
        """Mark an endpoint as a deprecated API. If an API class is decorated, all endpoints on the class will be
        automatically marked as deprecated.

        :param obj: Endpoint handler, API class, or API function
        """
        from ..base import APIBase

        if inspect.isclass(obj) and issubclass(obj, APIBase):
            obj.is_deprecated = True
            return obj
        return endpoint._apply_operations(obj, lambda h: setattr(h, "is_deprecated", True))

    @staticmethod
    def content_type(
        content_type: str,
    ) -> Callable[[EndpointHandler[P] | PendingHandler[P]], EndpointHandler[P] | PendingHandler[P]]:
        """Explicitly set Content-Type for this endpoint

        :param content_type: Content type to explicitly set
        """

        def wrapper(obj: EndpointHandler[P] | PendingHandler[P]) -> EndpointHandler[P] | PendingHandler[P]:
            return endpoint._apply_operations(obj, lambda h: setattr(h, "content_type", content_type))

        return wrapper

    @staticmethod
    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        """Convert a regular decorator to be usable on API functions. This supports both regular decorators and
        decorators with arguments

        Due to the way we encapsulate an API class function, the first argument of a regular decorator applied on our
        API function will be an EndpointHandler object instead of the decorated function. Decorating the decorator with
        this `endpoint.decorator` will make it usable on an API class function

        >>> # The decorator definition
        >>> @endpoint.decorator # This is what you need
        >>> def my_decorator(f):
        >>>     @wraps(f)
        >>>     def wrapper(*args, **kwargs):
        >>>         return f(*args, **kwargs)
        >>>     return wrapper

        >>> # Apply the decorator on an API function
        >>> @my_decorator   # This can be also done as @endpoint.decorator(my_decorator) instead
        >>> @endpoint.get("foo/bar")
        >>> def get_foo_bar(self):
        >>>    ...
        """

        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if (
                not kwargs
                and len(args) == 1
                and (isinstance(args[0], (EndpointHandler, PendingHandler)) or inspect.isfunction(args[0]))
            ):
                # Bare decorator: @my_decorator on EndpointHandler, PendingEndpoint, or plain API function
                return endpoint._apply_operations(args[0], lambda h: h.register_decorator(f))
            else:
                # Decorator with arguments: @my_decorator(arg1, arg2, ...)
                @wraps(f)
                def _wrapper(obj: Any) -> Any:
                    return endpoint._apply_operations(obj, lambda h: h.register_decorator(partial(f, *args, **kwargs)))

                return _wrapper

        return wrapper

    @staticmethod
    def _create(
        method: str, path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[[Callable[Concatenate[T, P], R]], EndpointHandler[P]]:
        """Returns an endpoint factory that creates an endpoint handler object, which will return an
        EndpointFunc object when accessing the associated API class function
        """

        def endpoint_factory(f: Callable[Concatenate[T, P], R] | PendingHandler[P]) -> EndpointHandler[P]:
            if isinstance(f, PendingHandler):
                handler: EndpointHandler[P] = EndpointHandler(
                    f.func, method, path, use_query_string=use_query_string, **default_raw_options
                )
                for modifier in f.deferred_operations:
                    modifier(handler)
                return handler
            return EndpointHandler(f, method, path, use_query_string=use_query_string, **default_raw_options)

        return endpoint_factory

    @staticmethod
    def _apply_operations(
        obj: EndpointHandler[P] | PendingHandler[P] | Callable[P, RestResponse], operation: DeferredOperation[P]
    ) -> Any:
        """Apply an endpoint operation immediately (EndpointHandler) or defer it (function / PendingEndpoint)

        :param obj: An EndpointHandler, PendingEndpoint, or a plain API function
        :param operation: An operation to apply to the final EndpointHandler
        """
        if isinstance(obj, EndpointHandler):
            operation(obj)
            return obj
        elif isinstance(obj, PendingHandler):
            obj.deferred_operations.append(operation)
            return obj
        elif inspect.isfunction(obj):
            pending_handler: PendingHandler[P] = PendingHandler(obj)
            pending_handler.deferred_operations.append(operation)
            return pending_handler
        else:
            raise TypeError(
                f"Expected an {EndpointHandler.__name__} or API function, got {type(obj).__name__}. "
                "Ensure @endpoint.<method>() is present in the decorator stack."
            )
