from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import cache, partial, update_wrapper, wraps
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar, ParamSpec, TypeAlias, TypeVar, Union, cast

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client import APIResponse, RestResponse
from common_libs.clients.rest_client.utils import retry_on
from common_libs.job_executor import Job, run_concurrent
from common_libs.lock import Lock
from common_libs.logging import get_logger
from httpx import HTTPError

import openapi_test_client.libraries.api.api_functions.utils.endpoint_function as endpoint_func_util
import openapi_test_client.libraries.api.api_functions.utils.endpoint_model as endpoint_model_util
import openapi_test_client.libraries.api.api_functions.utils.pydantic_model as pydantic_model_util
from openapi_test_client.libraries.api.api_classes import APIBase
from openapi_test_client.libraries.api.api_functions.executors import AsyncExecutor, SyncExecutor
from openapi_test_client.libraries.api.types import EndpointModel
from openapi_test_client.libraries.common.misc import generate_class_name

if TYPE_CHECKING:
    from common_libs.clients.rest_client import RestClient

    from openapi_test_client.clients import OpenAPIClient


__all__ = ["Endpoint", "EndpointFunc", "EndpointHandler", "endpoint"]


P = ParamSpec("P")
R = TypeVar("R")


_EndpointFunc = TypeVar(
    # TODO: Remove this
    # A workaround for https://youtrack.jetbrains.com/issue/PY-57765
    "_EndpointFunc",
    bound=Callable[..., RestResponse],
)
EndpointFunction: TypeAlias = Union[_EndpointFunc, "EndpointFunc", "SyncEndpointFunc", "AsyncEndpointFunc"]
EndpointDecorator: TypeAlias = Callable[[EndpointFunction], EndpointFunction]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Endpoint:  # noqa: PLW1641
    """An Endpoint class to hold various endpoint data associated to an API class function

    This is accessible via an EndpointFunc object (see docstrings of the `endpoint` class below).
    """

    tags: tuple[str, ...]
    api_class: type[APIBase]
    method: str
    path: str
    func_name: str
    model: type[EndpointModel]
    url: str | None = None  # Available only for an endpoint object accessed via an API client instance
    content_type: str | None = None
    is_public: bool = False
    is_documented: bool = True
    is_deprecated: bool = False

    def __str__(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, Endpoint) and str(self) == str(obj)

    def __call__(
        self,
        api_client: OpenAPIClient,
        *path_params: Any,
        quiet: bool = False,
        validate: bool = False,
        with_hooks: bool = True,
        raw_options: dict[str, Any] | None = None,
        **body_or_query_params: Any,
    ) -> APIResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint using the given API client

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param body_or_query_params: Request body or query parameters

        Example:
            >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
            >>>
            >>> client = DemoAppAPIClient()
            >>> r = client.Auth.login(username="foo", password="bar")
            >>> # Above API call can be also done directly from the endpoint object, if you need to:
            >>> endpoint = client.Auth.login.endpoint
            >>> r2 = endpoint(client, username="foo", password="bar")
        """
        api_class = self.api_class(api_client)
        endpoint_func: EndpointFunc = getattr(api_class, self.func_name)
        func_call = partial(
            endpoint_func,
            *path_params,
            quiet=quiet,
            with_hooks=with_hooks,
            validate=validate,
            raw_options=raw_options,
            **body_or_query_params,
        )
        if api_client.async_mode:
            return asyncio.run(func_call())
        else:
            return func_call()


class endpoint:
    """A class to convert an API class function to work as an EndpointFunc class object

    An EndpointFunc object can be accessed by the following two ways:
    - <API Clas>.<API class function>
    - <API Class instance>.<API class function>

    Example:
        >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
        >>> from openapi_test_client.clients.demo_app.api import DemoAppBaseAPI
        >>> from openapi_test_client.libraries.api.types import Unset
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
        return cast(EndpointFunction, obj)

    @staticmethod
    def is_public(obj: EndpointHandler | EndpointFunction) -> EndpointFunction:
        """Mark an endpoint as a public API that does not require authentication.
        The flag value is available with an Endpoint object's is_public attribute

        :param obj: Endpoint handler
        NOTE: EndpointFunction type was added for mypy only
        """
        assert isinstance(obj, EndpointHandler)
        obj.is_public = True
        return cast(EndpointFunction, obj)

    @staticmethod
    def is_deprecated(obj: EndpointHandler | type[APIBase] | EndpointFunction) -> EndpointFunction:
        """Mark an endpoint as a deprecated API. If an API class is decorated, all endpoints on the class will be
        automatically marked as deprecated.

        :param obj: Endpoint handler or API class
        NOTE: EndpointFunction type was added for mypy only
        """
        assert isinstance(obj, EndpointHandler) or (inspect.isclass(obj) and issubclass(obj, APIBase))
        obj.is_deprecated = True
        return cast(EndpointFunction, obj)

    @staticmethod
    def content_type(content_type: str) -> Callable[..., EndpointFunction]:
        """Explicitly set Content-Type for this endpoint

        :param content_type: Content type to explicitly set
        """

        def wrapper(endpoint_handler: EndpointHandler) -> EndpointHandler:
            assert isinstance(endpoint_handler, EndpointHandler)
            endpoint_handler.content_type = content_type
            return endpoint_handler

        return cast(Callable[..., EndpointFunction], wrapper)

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

        def wrapper(*args: Any, **kwargs: Any) -> EndpointHandler | Callable[[EndpointHandler], EndpointHandler]:
            if not kwargs and args and len(args) == 1 and isinstance(args[0], EndpointHandler):
                # This is a regular decorator
                endpoint_handler: EndpointHandler = args[0]
                endpoint_handler.register_decorator(cast(EndpointDecorator, f))
                return endpoint_handler
            else:
                # The decorator takes arguments
                def _wrapper(endpoint_handler: EndpointHandler) -> EndpointHandler:
                    endpoint_handler.register_decorator(cast(EndpointDecorator, partial(f, *args, **kwargs)))
                    return endpoint_handler

                return _wrapper

        return cast(EndpointDecorator | Callable[..., EndpointDecorator], wrapper)

    @staticmethod
    def request_wrapper(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return f(*args, **kwargs)

        return wrapper

    @staticmethod
    def _create(
        method: str, path: str, use_query_string: bool = False, **default_raw_options: Any
    ) -> Callable[..., EndpointFunc]:
        """Returns an endpoint factory that creates an endpoint handler object, which will return an
        EndpointFunc object when accessing the associated API class function
        """

        def endpoint_factory(f: Callable[..., RestResponse]) -> EndpointHandler:
            return EndpointHandler(f, method, path, use_query_string=use_query_string, **default_raw_options)

        return cast(Callable[..., EndpointFunc], endpoint_factory)


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
        key = (self.original_func.__name__, instance, owner)
        is_async = instance and instance.api_client.async_mode
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


def requires_instance(f: Callable[P, R]) -> Callable[P, R]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        self = cast(EndpointFunc, args[0])
        if self._instance is None:
            func_name = self._original_func.__name__ if f.__name__ == "__call__" else f.__name__
            raise TypeError(f"You can not access {func_name}() directly through the {self._owner.__name__} class.")
        return f(*args, **kwargs)

    return wrapper


class EndpointFunc:
    """Base class for Sync/Async Endpoint function classes"""

    executor: SyncExecutor | AsyncExecutor | None = None

    def __init__(self, endpoint_handler: EndpointHandler, instance: APIBase | None, owner: type[APIBase]):
        """Initialize endpoint function"""
        if not issubclass(owner, APIBase):
            raise NotImplementedError(f"Unsupported API class: {owner}")

        self.method = endpoint_handler.method
        self.path = endpoint_handler.path
        self.rest_client: RestClient | None
        self.api_client: OpenAPIClient | None
        if instance:
            self.api_client = instance.api_client
            self.rest_client = self.api_client.rest_client
        else:
            self.api_client = None
            self.rest_client = None

        # Control a retry in a request wrapper to prevent a loop
        self.retried = False

        self._instance: APIBase | None = instance
        self._owner: type[APIBase] = owner
        self._original_func: Callable[..., RestResponse] = endpoint_handler.original_func
        self._use_query_string = endpoint_handler.use_query_string
        self._raw_options = endpoint_handler.default_raw_options

        tags = (instance or owner).TAGs
        assert isinstance(tags, tuple)
        self.endpoint: Endpoint = Endpoint(  # make mypy happy
            tags,
            owner,
            self.method,
            self.path,
            self._original_func.__name__,
            self.model,
            url=f"{self.rest_client.base_url}{self.path}" if instance else None,
            content_type=endpoint_handler.content_type,
            is_public=endpoint_handler.is_public,
            is_documented=owner.is_documented and endpoint_handler.is_documented,
            is_deprecated=owner.is_deprecated or endpoint_handler.is_deprecated,
        )

        # Decorate the __call__ if request_wrapper is defined in the API class, or if decorators are registered.
        # If both request wrapper and endpoint decorators exist, endpoint decorators will be processed first
        if instance:
            my_class = type(self)
            if request_wrappers := instance.request_wrapper():
                for request_wrapper in request_wrappers[::-1]:
                    my_class.__call__ = request_wrapper(my_class.__call__)  # type: ignore[method-assign]
            for decorator in endpoint_handler.decorators:
                if isinstance(decorator, partial):
                    my_class.__call__ = decorator()(my_class.__call__)  # type: ignore[method-assign]
                else:
                    my_class.__call__ = decorator(my_class.__call__)  # type: ignore[method-assign]

    def __repr__(self) -> str:
        return f"{super().__repr__()}\n(mapped to: {self._original_func!r})"

    @requires_instance
    async def __call__(
        self,
        *path_params: Any,
        quiet: bool = False,
        validate: bool | None = None,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **body_or_query_params: Any,
    ) -> RestResponse:
        """Make an API call to the endpoint. This logic is commonly used for sync/acync API calls

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param body_or_query_params: Request body or query parameters
        """
        if validate is None:
            validate = pydantic_model_util.is_validation_mode()
        path = endpoint_func_util.validate_path_and_params(
            self, *path_params, validate=validate, raw_options=raw_options, **body_or_query_params
        )

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)

        # Make a request
        r = None
        exception = None
        try:
            # Call the original function first to make sure any custom function logic (if implemented) is executed.
            # If it returns a RestResponse obj, we will use it. If nothing is returned (the default behavior),
            # we will automatically make an API call
            # Undocumented endpoints manually added/updated by users might not always have **kwargs like the regular
            # endpoints updated/managed by our script. To avoid an error by giving unexpected keyword argument, we pass
            # parameters for rest client only when the user explicitly requests them
            kwargs: dict[str, Any] = {}
            if raw_options:
                kwargs.update(raw_options=raw_options)
            if quiet:
                kwargs.update(quiet=quiet)
            r = await self._call_original_func(path_params, body_or_query_params, kwargs)
            if r is not None:
                if not isinstance(r, RestResponse):
                    raise RuntimeError(f"Custom endpoint must return a RestResponse object, got {type(r).__name__}")
            else:
                params = endpoint_func_util.generate_rest_func_params(
                    self.endpoint,
                    body_or_query_params,
                    self.rest_client.client.headers,
                    quiet=quiet,
                    use_query_string=self._use_query_string,
                    is_validation_mode=validate,
                    **self._raw_options | (raw_options or {}),
                )
                r = await self._call_api_func(path, params)
            return r
        except HTTPError as e:
            exception = e
            raise
        except Exception:
            with_hooks = False
            raise
        finally:
            if with_hooks:
                try:
                    self._instance.post_request_hook(self.endpoint, r, exception, *path_params, **body_or_query_params)
                except AssertionError:
                    raise
                except Exception as e:
                    logger.exception(e)

    @property
    def model(self) -> type[EndpointModel]:
        """Return the dynamically created model of the endpoint"""
        return endpoint_model_util.create_endpoint_model(self)

    def help(self) -> None:
        """Display the API function definition"""
        help(self._original_func)

    def docs(self) -> None:
        """Display OpenAPI spec definition for this endpoint"""
        if api_spec_definition := self.get_usage():
            print(color(api_spec_definition, color_code=ColorCodes.YELLOW))  # noqa: T201
        else:
            print("Docs not available")  # noqa: T201

    @requires_instance
    def with_retry(
        self,
        *args: Any,
        condition: int | Sequence[int] | Callable[[RestResponse], bool] = lambda r: not r.ok,
        num_retry: int = 1,
        retry_after: float | int | Callable[[RestResponse], float | int] = 5,
        **kwargs: Any,
    ) -> APIResponse:
        """Make an API call with retry conditions

        :param args: Positional arguments passed to __call__()
        :param condition: Either status code(s) or a function that takes response object as the argument
        :param num_retry: The max number of retries
        :param retry_after: A short wait time in seconds before a retry
        :param kwargs: Keyword arguments passed to __call__()
        """
        f = retry_on(
            condition,
            num_retry=num_retry,
            retry_after=retry_after,
            safe_methods_only=False,
            _async_mode=self.api_client.async_mode,
        )(self.__call__)
        return f(*args, **kwargs)

    @requires_instance
    def with_lock(self, *args: Any, lock_name: str | None = None, **kwargs: Any) -> APIResponse:
        """Make an API call with lock

        The lock will be applied on the API endpoint function level, which means any other API calls in the same/other
        processes using the same API function will wait until after lock is acquired

        See __call__() for supported function arguments

        :param args: Positional arguments passed to __call__()
        :param lock_name: Explicitly specify the lock name. Use this when the same lock needs to be shared among
                          multiple endpoints
        :param kwargs: Keyword arguments passed to __call__()
        """
        if not lock_name:
            lock_name = f"{self._instance.app_name}-{type(self._instance).__name__}.{self._original_func.__name__}"
        with Lock(lock_name):
            return self(*args, **kwargs)

    def get_usage(self) -> str | None:
        """Get OpenAPI spec definition for the endpoint"""
        if self.api_client and self.endpoint.is_documented:
            return self.api_client.api_spec.get_endpoint_usage(self.endpoint)

    @staticmethod
    @cache
    def _create(api_class: type[APIBase], orig_func: Callable[..., Any], async_mode: bool) -> type[EndpointFunc]:
        """Dynamically create an EndpointFunc class for the given endpoint function"""
        base_class = AsyncEndpointFunc if async_mode else SyncEndpointFunc
        class_name = f"{api_class.__name__}{generate_class_name(orig_func.__name__, suffix=EndpointFunc.__name__)}"
        return type(class_name, (base_class,), {})

    async def _call_original_func(
        self, path_params: tuple[str, ...], body_or_query_params: dict[str, Any], kwargs: dict[str, Any]
    ) -> RestResponse:
        r = self._original_func(self._instance, *path_params, **body_or_query_params, **kwargs)
        if self.api_client.async_mode and asyncio.iscoroutine(r):
            # The original function is a not an async function but rest_client used inside the original function is
            # AsyncRestClient, which means the returned value will be a coroutine. We can await it and get the actual
            # value in here
            r = await r
        return r

    async def _call_api_func(self, path: str, params: dict[str, Any]) -> RestResponse:
        if self.api_client.async_mode:
            assert isinstance(self, AsyncEndpointFunc)
            assert isinstance(self.executor, AsyncExecutor)
            return await self.executor.execute(self, path, params)
        else:
            assert isinstance(self, SyncEndpointFunc)
            assert isinstance(self.executor, SyncExecutor)
            return self.executor.execute(self, path, params)


class SyncEndpointFunc(EndpointFunc):
    """Endpoint function class (Sync)

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

    executor = SyncExecutor()

    @requires_instance
    @wraps(EndpointFunc.__call__)
    def __call__(self, *args: Any, **kwargs: Any) -> RestResponse:
        """Make a sync API call to the endpoint"""
        return asyncio.run(super().__call__(*args, **kwargs))

    @requires_instance
    def with_concurrency(self, *args: Any, num: int = 2, **kwargs: Any) -> list[APIResponse]:
        """Concurrently make duplicated API calls to the endpoint

        :param args: Positional arguments passed to __call__()
        :param num: Number of concurrent API calls
        :param kwargs: Keyword arguments passed to __call__()
        """
        return run_concurrent([Job(self.__call__, args, kwargs) for _ in range(num)])

    @contextmanager
    @requires_instance
    def stream(
        self,
        *path_params: Any,
        quiet: bool = False,
        validate: bool | None = None,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **body_or_query_params: Any,
    ) -> Generator[RestResponse]:
        """Stream the response"""
        if validate is None:
            validate = pydantic_model_util.is_validation_mode()
        path = endpoint_func_util.validate_path_and_params(
            self, *path_params, validate=validate, raw_options=raw_options, **body_or_query_params
        )

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)

        # Make a request
        r = None
        exception = None
        try:
            params = endpoint_func_util.generate_rest_func_params(
                self.endpoint,
                body_or_query_params,
                self.rest_client.client.headers,
                quiet=quiet,
                use_query_string=self._use_query_string,
                is_validation_mode=validate,
                **self._raw_options | (raw_options or {}),
            )
            with self.executor.execute_stream(self, path, params) as r:
                yield r
        except HTTPError as e:
            exception = e
            raise
        except (Exception, KeyboardInterrupt):
            with_hooks = False
            raise
        # post-request hook
        finally:
            if with_hooks:
                try:
                    self._instance.post_request_hook(self.endpoint, r, exception, *path_params, **body_or_query_params)
                except AssertionError:
                    raise
                except Exception as e:
                    logger.exception(e)


class AsyncEndpointFunc(EndpointFunc):
    """Endpoint function class (Async)

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

    executor = AsyncExecutor()

    @requires_instance
    @wraps(EndpointFunc.__call__)
    async def __call__(self, *args: Any, **kwargs: Any) -> RestResponse:
        """Make an async API call to the endpoint"""
        return await super().__call__(*args, **kwargs)

    @requires_instance
    async def with_concurrency(self, *args: Any, num: int = 2, **kwargs: Any) -> list[APIResponse]:
        """Concurrently make duplicated API calls to the endpoint

        :param args: Positional arguments passed to __call__()
        :param num: Number of concurrent API calls
        :param kwargs: Keyword arguments passed to __call__()
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self(*args, **kwargs)) for _ in range(num)]
        return [t.result() for t in tasks]

    @asynccontextmanager
    @requires_instance
    async def stream(
        self,
        *path_params: Any,
        quiet: bool = False,
        validate: bool | None = None,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **body_or_query_params: Any,
    ) -> AsyncGenerator[RestResponse]:
        """Stream response from an API call to the endpoint

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param body_or_query_params: Request body or query parameters
        """
        if validate is None:
            validate = pydantic_model_util.is_validation_mode()
        path = endpoint_func_util.validate_path_and_params(
            self, *path_params, validate=validate, raw_options=raw_options, **body_or_query_params
        )

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)

        # Make a request
        r = None
        exception = None
        try:
            params = endpoint_func_util.generate_rest_func_params(
                self.endpoint,
                body_or_query_params,
                self.rest_client.client.headers,
                quiet=quiet,
                use_query_string=self._use_query_string,
                is_validation_mode=validate,
                **self._raw_options | (raw_options or {}),
            )
            async with self.executor.execute_stream(self, path, params) as r:
                yield r
        except HTTPError as e:
            exception = e
            raise
        except Exception:
            with_hooks = False
            raise
        finally:
            if with_hooks:
                try:
                    self._instance.post_request_hook(self.endpoint, r, exception, *path_params, **body_or_query_params)
                except AssertionError:
                    raise
                except Exception as e:
                    logger.exception(e)


if TYPE_CHECKING:
    # For making IDE happy
    # TODO: Remove this
    EndpointFunc: TypeAlias = _EndpointFunc | EndpointFunc | SyncEndpointFunc | AsyncEndpointFunc  # type: ignore[no-redef]
