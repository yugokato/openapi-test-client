from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import partial, update_wrapper, wraps
from threading import RLock
from typing import TYPE_CHECKING, Any, ClassVar, Concatenate, ParamSpec, TypeAlias, TypeVar, cast

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.utils import retry_on
from common_libs.lock import Lock
from common_libs.logging import get_logger
from pydantic import ValidationError
from requests.exceptions import RequestException

import openapi_test_client.libraries.api.api_functions.utils.endpoint_function as endpoint_func_util
import openapi_test_client.libraries.api.api_functions.utils.endpoint_model as endpoint_model_util
import openapi_test_client.libraries.api.api_functions.utils.pydantic_model as pydantic_model_util
from openapi_test_client.libraries.api.api_classes import APIBase
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
    # A workaound for https://youtrack.jetbrains.com/issue/PY-57765
    "_EndpointFunc",
    bound=Callable[..., RestResponse],
)
EndpointFunction: TypeAlias = _EndpointFunc | "EndpointFunc"
EndpointDecorator: TypeAlias = Callable[[EndpointFunction], EndpointFunction]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Endpoint:
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
        requests_lib_options: dict[str, Any] | None = None,
        **params: Any,
    ) -> RestResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint using the given API client

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param requests_lib_options: Raw request options passed to the requests library's Session.request()
        :param params: Request body or query parameters

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
        return endpoint_func(
            *path_params,
            quiet=quiet,
            with_hooks=with_hooks,
            validate=validate,
            requests_lib_options=requests_lib_options,
            **params,
        )


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
    def get(path: str, **default_requests_lib_options: Any) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a GET API function

        :param path: The endpoint path
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create("get", path, use_query_string=True, **default_requests_lib_options)

    @staticmethod
    def post(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a POST API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "post",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def delete(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a DELETE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "delete",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def put(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a PUT API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "put",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def patch(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for a PATCH API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "patch",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def options(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an OPTIONS API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "options",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def head(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an HEAD API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "head",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

    @staticmethod
    def trace(
        path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunction]:
        """Returns a decorator that generates an endpoint handler for an TRACE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param default_requests_lib_options: Default request options passed to the requests library's Session.request()
        """
        return endpoint._create(
            "trace",
            path,
            use_query_string=use_query_string,
            **default_requests_lib_options,
        )

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
        method: str, path: str, use_query_string: bool = False, **default_requests_lib_options: Any
    ) -> Callable[..., EndpointFunc]:
        """Returns an endpoint factory that creates an endpoint handler object, which will return an
        EndpointFunc object when accessing the associated API class function
        """

        def endpoit_factory(f: Callable[..., RestResponse]) -> EndpointHandler:
            return EndpointHandler(
                f,
                method,
                path,
                use_query_string=use_query_string,
                **default_requests_lib_options,
            )

        return cast(Callable[..., EndpointFunc], endpoit_factory)


class EndpointHandler:
    """A class to encapsulate each API class function (original function) inside a dynamically generated
    EndpointFunc class

    An instance of EndpointHandler class works like a proxy to an EndpointFunc object when an API class function is
    called, which makes the original API function to behave as an EndpointFunc class object instead.
    Each EndpointFunc class will be named in the format of: <APIClassName><APIFunctionName>EndpointFunc

    eg: Accessing <class AuthAPI>.login will return AuthAPILoginEndpointFunc class object
    """

    # cache endpoint function objects
    _endpoint_functions: ClassVar = {}
    _lock = RLock()

    def __init__(
        self,
        original_func: Callable[..., RestResponse],
        method: str,
        path: str,
        use_query_string: bool = False,
        **default_requests_lib_options: Any,
    ) -> None:
        self.original_func = original_func
        self.method = method
        self.path = path
        self.use_query_string = use_query_string
        self.default_requests_lib_options = default_requests_lib_options

        # Will be set via @endpoint.<decorator_name>
        self.content_type: str | None = None  # application/json by default
        self.is_public = False
        self.is_documented = True
        self.is_deprecated = False
        self.__decorators: list[EndpointDecorator] = []

    def __get__(self, instance: APIBase | None, owner: type[APIBase]) -> EndpointFunc:
        """Return an EndpointFunc object"""
        key = (self.original_func.__name__, instance, owner)
        with EndpointHandler._lock:
            if not (endpoint_func := EndpointHandler._endpoint_functions.get(key)):
                endpoint_func_name = (
                    f"{owner.__name__}{generate_class_name(self.original_func.__name__, suffix=EndpointFunc.__name__)}"
                )
                EndpointFuncClass = type(endpoint_func_name, (EndpointFunc,), {})
                endpoint_func = EndpointFuncClass(self, instance, owner)
                EndpointHandler._endpoint_functions[key] = update_wrapper(endpoint_func, self.original_func)
        return cast(EndpointFunc, endpoint_func)

    @property
    def decorators(self) -> list[EndpointDecorator]:
        """Returns decorators that should be applied on an endpoint function"""
        return self.__decorators

    def register_decorator(self, *decorator: EndpointDecorator) -> None:
        """Register a decorator that will be applied on an endpoint function"""
        self.__decorators.extend([d for d in decorator])


def requires_instance(f: Callable[Concatenate[EndpointFunc, P], R]) -> Callable[Concatenate[EndpointFunc, P], R]:
    @wraps(f)
    def wrapper(self: EndpointFunc, *args: P.args, **kwargs: P.kwargs) -> R:
        if self._instance is None:
            func_name = self._original_func.__name__ if f.__name__ == "__call__" else f.__name__
            raise TypeError(f"You can not access {func_name}() directly through the {self._owner.__name__} class.")
        return f(self, *args, **kwargs)

    return wrapper


class EndpointFunc:
    """Endpoint function class

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

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
        self._requests_lib_options = endpoint_handler.default_requests_lib_options

        tags = (instance or owner).TAGs
        assert isinstance(tags, tuple)
        self.endpoint: Endpoint = Endpoint(  # make mypy happy
            tags,
            owner,
            self.method,
            self.path,
            self._original_func.__name__,
            self.model,
            url=f"{self.rest_client.url_base}{self.path}" if instance else None,
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
    def __call__(
        self,
        *path_params: Any,
        quiet: bool = False,
        validate: bool | None = None,
        with_hooks: bool | None = True,
        requests_lib_options: dict[str, Any] | None = None,
        **params: Any,
    ) -> RestResponse:
        """Make an API call to the endpoint

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param requests_lib_options: Raw request options passed to the requests library's Session.request()
        :param params: Request body or query parameters
        """
        if validate is None:
            validate = pydantic_model_util.is_validation_mode()

        if self.endpoint.is_deprecated:
            logger.warning(f"DEPRECATED: '{self.endpoint}' is deprecated")

        # Fill path variables
        try:
            completed_path = endpoint_func_util.complete_endpoint(self.endpoint, path_params)
        except ValueError as e:
            msg = str(e)
            if api_spec_definition := self.get_usage():
                msg = f"{e!s}\n{color(api_spec_definition, color_code=ColorCodes.YELLOW)}"
            raise ValueError(msg) from None

        # Check if parameters used are expected for the endpoint. If not, it is an indication that the API function is
        # not up-to-date.
        endpoint_func_util.check_params(self.endpoint, params, requests_lib_options=requests_lib_options)

        if validate:
            # Perform Pydantic validation in strict mode against parameters
            try:
                endpoint_func_util.validate_params(self.endpoint, params)
            except ValidationError as e:
                raise ValueError(
                    color(f"Request parameter validation failed.\n{e}", color_code=ColorCodes.RED)
                ) from None

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **params)

        # Make a request
        r = None
        request_exception = None
        try:
            # Call the original function first to make sure any custom function logic (if implemented) is executed.
            # If it returns a RestResponse obj, we will use it. If nothing is returned (the default behavior),
            # we will automatically make an API call
            kwargs: dict[str, Any] = {}
            # Undocumented endpoints manually added/updated by users might not always have **kwargs like the regular
            # endpoints updated/managed by our script. To avoid an error by giving unexpected keyword argument, we pass
            # paramters for rest client only when the user explicitly requests them
            if requests_lib_options:
                kwargs.update(requests_lib_options=requests_lib_options)
            if quiet:
                kwargs.update(quiet=quiet)
            r = self._original_func(self._instance, *path_params, **params, **kwargs)
            if r is not None:
                if not isinstance(r, RestResponse):
                    raise RuntimeError(
                        f"Detected an unexpected return value from {self._original_func.__name__}(). If you implements "
                        f"a custom API function logic and return something, the returned value MUST be a "
                        f"{RestResponse.__name__} object, not {type(r).__name__}"
                    )
            else:
                # use the copy since we cache the request function
                raw_requests_lib_options = deepcopy(self._requests_lib_options)
                if requests_lib_options:
                    raw_requests_lib_options.update(requests_lib_options)
                if raw_requests_lib_options.get("stream"):
                    logger.info("stream=True was specified")
                rest_func = getattr(self.rest_client, f"_{self.method}")
                rest_func_params = endpoint_func_util.generate_rest_func_params(
                    self.endpoint,
                    params,
                    self.rest_client.session.headers,
                    quiet=quiet,
                    use_query_string=self._use_query_string,
                    is_validation_mode=validate,
                    **raw_requests_lib_options,
                )
                r = rest_func(completed_path, **rest_func_params)
            return r
        except RequestException as e:
            request_exception = e
            raise
        except (Exception, KeyboardInterrupt):
            with_hooks = False
            raise
        # post-request hook
        finally:
            if with_hooks:
                try:
                    self._instance.post_request_hook(self.endpoint, r, request_exception, *path_params, **params)
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
        retry_after: float = 5,
        **kwargs: Any,
    ) -> RestResponse:
        """Make an API call with retry conditions

        :param args: Positional arguments passed to __call__()
        :param condition: Either status code(s) or a function that takes response object as the argument
        :param num_retry: The max number of retries
        :param retry_after: A short wait time in seconds before a retry
        :param kwargs: Keyword arguments passed to __call__()
        """
        f = retry_on(condition, num_retry=num_retry, retry_after=retry_after, safe_methods_only=False)(self)
        return f(*args, **kwargs)

    @requires_instance
    def with_lock(self, *args: Any, lock_name: str | None = None, **kwargs: Any) -> RestResponse:
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


if TYPE_CHECKING:
    # For making IDE happy
    # TODO: Remove this
    EndpointFunc: TypeAlias = _EndpointFunc | EndpointFunc  # type: ignore[no-redef]
