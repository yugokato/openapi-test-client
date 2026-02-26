from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import partial, wraps
from typing import TYPE_CHECKING, Any

from common_libs.clients.rest_client import RestResponse

from openapi_test_client.libraries.core.api_classes import APIBase
from openapi_test_client.libraries.core.endpoints.endpoint_handler import EndpointHandler

if TYPE_CHECKING:
    from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointDecorator, EndpointFunction

__all__ = ["endpoint"]


class endpoint:
    """An endpoint factory that converts a wrapped API class function to a dynamically-created EndpointFunc instance

    An EndpointFunc instance can be accessed by the following two ways:
    - class-level:    <API Class>.<API class function>
    - instance-level: <API Class instance>.<API class function>

    Example:
        >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
        >>> from openapi_test_client.clients.demo_app.api import DemoAppBaseAPI
        >>> from openapi_test_client.libraries.core.types import Unset
        >>>
        >>> class AuthAPI(DemoAppBaseAPI):
        >>>     @endpoint.post("/v1/login")
        >>>     def login(self, *, username: str = Unset, password: str = Unset, **kwargs: Any) -> RestResponse:
        >>>         ...
        >>>
        >>> client = DemoAppAPIClient()
        >>> type(client.Auth.login)
        <class 'openapi_test_client.libraries.api.api_functions.endpoint.AuthAPILoginEndpointFunc'>
        >>> type(AuthAPI.login)
        <class 'openapi_test_client.libraries.api.api_functions.endpoint.AuthAPILoginEndpointFunc'>
        >>> isinstance(client.Auth.login, EndpointFunc) and isinstance(AuthAPI.login, EndpointFunc)
        True
        >>> client.Auth.login.endpoint
        Endpoint(tags=('Auth',), api_class=<class 'openapi_test_client.clients.demo_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url='http://127.0.0.1:5000/v1/auth/login', content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> AuthAPI.login.endpoint
        Endpoint(tags=('Auth',), api_class=<class 'openapi_test_client.clients.demo_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url=None, content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> str(client.Auth.login.endpoint)
        'POST /v1/auth/login'
        >>> str(AuthAPI.login.endpoint)
        'POST /v1/auth/login'
        >>> client.Auth.login.endpoint.path
        '/v1/auth/login'
        >>> client.Auth.login.endpoint.url
        'http://127.0.0.1:5000/v1/auth/login'

    """  # noqa: E501

    @staticmethod
    def get(path: str, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a GET API function

        :param path: The endpoint path
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("get", path, use_query_string=True, **default_raw_options)

    @staticmethod
    def post(path: str, use_query_string: bool = False, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
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
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a DELETE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("delete", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def put(path: str, use_query_string: bool = False, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a PUT API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("put", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def patch(path: str, use_query_string: bool = False, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
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
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an OPTIONS API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("options", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def head(path: str, use_query_string: bool = False, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an HEAD API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("head", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def trace(path: str, use_query_string: bool = False, **default_raw_options: Any) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an TRACE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_raw_options: Raw request options passed to the underlying HTTP library
        """
        return endpoint._create("trace", path, use_query_string=use_query_string, **default_raw_options)

    @staticmethod
    def undocumented(obj: EndpointHandler | type[APIBase] | EndpointFunction) -> EndpointFunction:
        """Mark an endpoint as undocumented. If an API class is decorated, all endpoints on the class will be
        automatically marked as undocumented.
        The flag value is available with an Endpoint object's is_documented attribute

        :param obj: Endpoint handler or API class
        NOTE: EndpointFunction type was added for mypy only
        """
        assert isinstance(obj, EndpointHandler) or (inspect.isclass(obj) and issubclass(obj, APIBase))
        obj.is_documented = False
        return obj

    @staticmethod
    def is_public(obj: EndpointHandler | EndpointFunction) -> EndpointFunction:
        """Mark an endpoint as a public API that does not require authentication.
        The flag value is available with an Endpoint object's is_public attribute

        :param obj: Endpoint handler
        NOTE: EndpointFunction type was added for mypy only
        """
        assert isinstance(obj, EndpointHandler)
        obj.is_public = True
        return obj

    @staticmethod
    def is_deprecated(obj: EndpointHandler | type[APIBase] | EndpointFunction) -> EndpointFunction:
        """Mark an endpoint as a deprecated API. If an API class is decorated, all endpoints on the class will be
        automatically marked as deprecated.

        :param obj: Endpoint handler or API class
        NOTE: EndpointFunction type was added for mypy only
        """
        assert isinstance(obj, EndpointHandler) or (inspect.isclass(obj) and issubclass(obj, APIBase))
        obj.is_deprecated = True
        return obj

    @staticmethod
    def content_type(content_type: str) -> Callable[..., EndpointFunction]:
        """Explicitly set Content-Type for this endpoint

        :param content_type: Content type to explicitly set
        """

        def wrapper(endpoint_handler: EndpointHandler) -> EndpointHandler:
            assert isinstance(endpoint_handler, EndpointHandler)
            endpoint_handler.content_type = content_type
            return endpoint_handler

        return wrapper

    @staticmethod
    def decorator(
        f: EndpointDecorator | Callable[..., EndpointDecorator],
    ) -> EndpointDecorator | Callable[..., EndpointDecorator]:
        """Convert a regular decorator to be usable on API functions. This supports both regular decorators and
        decorators with arugments

        Due to the way we encupsulate an API class function, the first argument of a regular decorator applied on our
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
        def wrapper(*args: Any, **kwargs: Any) -> EndpointHandler | Callable[[EndpointHandler], EndpointHandler]:
            if not kwargs and args and len(args) == 1 and isinstance(args[0], EndpointHandler):
                # This is a regular decorator
                endpoint_handler: EndpointHandler = args[0]
                endpoint_handler.register_decorator(f)
                return endpoint_handler
            else:
                # The decorator takes arguments
                @wraps(f)
                def _wrapper(endpoint_handler: EndpointHandler) -> EndpointHandler:
                    endpoint_handler.register_decorator(partial(f, *args, **kwargs))
                    return endpoint_handler

                return _wrapper

        return wrapper

    @staticmethod
    def _create(
        method: str, path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns an endpoint factory that creates an endpoint handler object, which will return an
        EndpointFunc object when accessing the associated API class function
        """

        def endpoint_factory(f: Callable[..., RestResponse]) -> EndpointHandler:
            return EndpointHandler(f, method, path, use_query_string=use_query_string, **default_raw_options)

        return endpoint_factory
