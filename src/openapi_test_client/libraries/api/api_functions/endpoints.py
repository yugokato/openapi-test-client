from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import partial, update_wrapper, wraps
from typing import TYPE_CHECKING, Any, Callable, Optional, ParamSpec, Sequence, TypeVar, cast

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.utils import retry_on
from common_libs.logging import get_logger
from pydantic import ValidationError
from requests.exceptions import RequestException

import openapi_test_client.libraries.api.api_functions.utils.endpoint_function as endpoint_func_util
import openapi_test_client.libraries.api.api_functions.utils.endpoint_model as endpoint_model_util
import openapi_test_client.libraries.api.api_functions.utils.pydantic_model as pydantic_model_util
from openapi_test_client.libraries.api import APIBase
from openapi_test_client.libraries.api.types import EndpointModel
from openapi_test_client.libraries.common.misc import generate_class_name

if TYPE_CHECKING:
    from common_libs.clients.rest_client import RestClient

    from openapi_test_client.clients import APIClientType
    from openapi_test_client.libraries.api.api_classes import APIClassType


__all__ = ["Endpoint", "EndpointFunc", "endpoint"]


P = ParamSpec("P")
OriginalFunc = TypeVar("OriginalFunc")

logger = get_logger(__name__)


@dataclass(frozen=True)
class Endpoint:
    """An Endpoint class to hold various endpoint data associated to an API class function

    This is accessible via an EndpointFunc object (see docstrings of the `endpoint` class below).
    """

    tags: list[str]
    api_class: type[APIClassType]
    method: str
    path: str
    func_name: str
    model: type[EndpointModel]
    url: Optional[str] = None  # Available only for an endpoint object accessed via an API client instance
    content_type: Optional[str] = None
    is_public: bool = False
    is_documented: bool = True
    is_deprecated: bool = False

    def __str__(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, Endpoint) and str(self) == str(obj)

    def __call__(
        self,
        api_client: APIClientType,
        *path_params,
        quiet: bool = False,
        with_hooks: bool = True,
        **params,
    ) -> RestResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint using the given API client

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param with_hooks: Invoke pre/post request hooks
        :param params: Request body or query parameters

        Example:
            >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
            >>>
            >>> client = DemoAppAPIClient()
            >>> r = client.AUTH.login(username="foo", password="bar")
            >>> # Above API call can be also done directly from the endpoint object, if you need to:
            >>> endpoint = client.AUTH.login.endpoint
            >>> r2 = endpoint(client, username="foo", password="bar")
        """
        endpoint_func: EndpointFunc = getattr(self.api_class(api_client), self.func_name)
        return endpoint_func(*path_params, quiet=quiet, with_hooks=with_hooks, **params)


class endpoint:
    """A class to convert an API class function to work as an EndpointFunc class object

    An EndpointFunc object can be accessed by the following two ways:
    - <API Clas>.<API class function>
    - <API Class instance>.<API class function>

    Example:
        >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
        >>> from openapi_test_client.clients.demo_app.api import DemoAppBaseAPI
        >>>
        >>> class AuthAPI(DemoAppBaseAPI):
        >>>     @endpoint.post("/v1/login")
        >>>     def login(self, *, username: str, password: str, **params):
        >>>         ...
        >>>
        >>> client = DemoAppAPIClient()
        >>> type(client.AUTH.login)
        <class 'openapi_test_client.libraries.api.api_functions.endpoint.AuthAPILoginEndpointFunc'>
        >>> type(AuthAPI.login)
        <class 'openapi_test_client.libraries.api.api_functions.endpoint.AuthAPILoginEndpointFunc'>
        >>> isinstance(client.AUTH.login, EndpointFunc) and isinstance(AuthAPI.login, EndpointFunc)
        True
        >>> client.AUTH.login.endpoint
        Endpoint(tags=['Auth'], api_class=<class 'openapi_test_client.clients.demo_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url='http://127.0.0.1:5000/v1/auth/login', content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> AuthAPI.login.endpoint
        Endpoint(tags=['Auth'], api_class=<class 'openapi_test_client.clients.demo_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.AuthAPILoginEndpointModel'>, url=None, content_type=None, is_public=False, is_documented=True, is_deprecated=False)
        >>> str(client.AUTH.login.endpoint)
        'POST /v1/auth/login'
        >>> str(AuthAPI.login.endpoint)
        'POST /v1/auth/login'
        >>> client.AUTH.login.endpoint.path
        '/v1/auth/login'
        >>> client.AUTH.login.endpoint.url
        'http://127.0.0.1:5000/v1/auth/login'

    """

    @staticmethod
    def get(path: str, **requests_lib_options) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for a GET API function

        :param path: The endpoint path
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate("get", path, use_query_string=True, **requests_lib_options)

    @staticmethod
    def post(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for a POST API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "post",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def delete(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for a DELETE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "delete",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def put(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for a PUT API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "put",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def patch(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for a PATCH API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "patch",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def options(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for an OPTIONS API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "options",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def head(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for an HEAD API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "head",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def trace(
        path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler for an TRACE API function

        :param path: The endpoint path
        :param use_query_string: Force send all parameters as query strings instead of request body
                                 NOTE: Parameters annotated with Annotated[type, "query"] will always be sent as query
                                       strings regardless of this option
        :param requests_lib_options: Raw request options passed to the requests library
        """
        return endpoint._generate(
            "trace",
            path,
            use_query_string=use_query_string,
            **requests_lib_options,
        )

    @staticmethod
    def undocumented(obj: EndpointHandler | APIClassType) -> EndpointHandler | APIClassType:
        """Mark an endpoint as undocumented. If an API class is decorated, all endpoints on the class will be
        automatically marked as undocumented.
        The flag value is available with an Endpoint object's is_documented attribute
        """
        obj.is_documented = False
        return obj

    @staticmethod
    def is_public(endpoint_handler: EndpointHandler) -> EndpointHandler | APIClassType:
        """Mark an endpoint as a public API that does not require authentication.
        The flag value is available with an Endpoint object's is_public attribute
        """
        endpoint_handler.is_public = True
        return endpoint_handler

    @staticmethod
    def is_deprecated(obj: EndpointHandler | APIClassType) -> EndpointHandler | APIClassType:
        """Mark an endpoint as a deprecated API. If an API class is decorated, all endpoints on the class will be
        automatically marked as deprecated.
        """
        obj.is_deprecated = True
        return obj

    @staticmethod
    def content_type(content_type: str) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Explicitly set Content-Type for this endpoint"""

        def decorator_with_arg(obj: EndpointHandler | APIClassType) -> EndpointHandler | APIClassType:
            obj.content_type = content_type
            return obj

        return decorator_with_arg

    @staticmethod
    def decorator(f: Callable[P, Any]) -> Callable[P, OriginalFunc | EndpointFunc]:
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
        >>> @my_decorator   # This can be also done as @endpoint.decorate(my_decorator) instead
        >>> @endpoint.get("foo/bar")
        >>> def get_foo_bar(self):
        >>>    ...
        """

        def wrapper(*args, **kwargs) -> EndpointHandler | Callable[P, OriginalFunc | EndpointHandler]:
            if not kwargs and args and len(args) == 1 and isinstance(args[0], EndpointHandler):
                # This is a regular decorator
                endpoint_handler: EndpointHandler = args[0]
                endpoint_handler.register_decorator(f)
                return endpoint_handler
            else:
                # The decorator takes arguments
                def _wrapper(endpoint_handler: EndpointHandler) -> EndpointHandler:
                    endpoint_handler.register_decorator(partial(f, *args, **kwargs))
                    return endpoint_handler

                return _wrapper

        return wrapper

    @staticmethod
    def request_wrapper(f: Callable[P, Any]) -> Callable[P, OriginalFunc | EndpointFunc]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> OriginalFunc | EndpointFunc:
            return f(*args, **kwargs)

        return wrapper

    @staticmethod
    def _generate(
        method: str, path: str, use_query_string: bool = False, **requests_lib_options
    ) -> Callable[P, OriginalFunc | EndpointFunc]:
        """Returns a decorator that generates an endpoint handler object, which will return an EndpointFunction object
        when accessing an API class function
        """

        def decorator(f):
            return cast(
                EndpointFunc,
                EndpointHandler(
                    f,
                    method,
                    path,
                    use_query_string=use_query_string,
                    **requests_lib_options,
                ),
            )

        return decorator


class EndpointHandler:
    """A class to encapsulate each API class function (original function) inside a dynamically generated
    EndpointFunc class

    An instance of EndpointHandler class works like a proxy to an EndpointFunc object when an API class function is
    called, which makes the original API function to behave as an EndpointFunc class object instead.
    Each EndpointFunc class will be named in the format of: <APIClassName><APIFunctionName>EndpointFunc

    eg: Accessing <class AuthAPI>.login will return AuthAPILoginEndpointFunc class object
    """

    # cache endpoint function objects
    _endpoint_functions = {}

    def __init__(
        self,
        original_func: Callable[P, RestResponse],
        method: str,
        path: str,
        use_query_string: bool = False,
        **requests_lib_options,
    ):
        self.original_func = original_func
        self.method = method
        self.path = path
        self.use_query_string = use_query_string
        self.requests_lib_options = requests_lib_options
        self.content_type = None  # Will be set by @endpoint.content_type decorator (or application/json by default)
        self.is_public = False
        self.is_documented = True
        self.is_deprecated = False
        self.__decorators = []

    def __get__(self, instance: Optional[APIClassType], owner: type[APIClassType]) -> EndpointFunc:
        """Return an EndpointFunc object"""
        key = (self.original_func.__name__, instance, owner)
        if not (endpoint_func := EndpointHandler._endpoint_functions.get(key)):
            endpoint_func_name = (
                f"{owner.__name__}{generate_class_name(self.original_func.__name__, suffix=EndpointFunc.__name__)}"
            )
            endpoint_func_class = type(
                endpoint_func_name,
                (EndpointFunc,),
                {},
            )
            endpoint_func = endpoint_func_class(self, instance, owner)
            EndpointHandler._endpoint_functions[key] = endpoint_func
        return cast(EndpointFunc, update_wrapper(endpoint_func, self.original_func))

    @property
    def decorators(self) -> list[Callable]:
        """Returns decorators that should be applied on an endpoint function"""
        return self.__decorators

    def register_decorator(self, *decorator):
        """Register a decorator that will be applied on an endpoint function"""
        self.__decorators.extend([d for d in decorator])


class EndpointFunc:
    """Endpoint function class

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

    def __init__(self, endpoint_handler: EndpointHandler, instance: Optional[APIClassType], owner: type[APIClassType]):
        """Initialize endpoint function"""
        if not issubclass(owner, APIBase):
            raise NotImplementedError(f"Unsupported API class: {owner}")

        self.method = endpoint_handler.method
        self.path = endpoint_handler.path
        self.rest_client: Optional[RestClient]
        if instance:
            self.api_client = instance.api_client
            self.rest_client = self.api_client.rest_client
        else:
            self.api_client = None
            self.rest_client = None

        # Control a retry in a request wrapper to prevent a loop
        self.retried = False

        self._original_func = endpoint_handler.original_func
        self._instance = instance
        self._owner = owner
        self._use_query_string = endpoint_handler.use_query_string
        self._requests_lib_options = endpoint_handler.requests_lib_options

        # <API class>.TAGs can be the ABC class's property object until after it is defined in an actual
        # API class. To make the sorting of endpoint objects during an initialization of API
        # classes work using (endpoint.tag, endpoint.method, endpoint.path) key, assign an empty
        # list if TAGs is not defined
        if not isinstance(tags := (instance or owner).TAGs, list):
            tags = []
        self.endpoint = Endpoint(
            tags,
            owner,
            self.method,
            self.path,
            self._original_func.__name__,
            self.model,
            url=f"{self.rest_client.url_base}{self.path }" if instance else None,
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
                    my_class.__call__ = request_wrapper(my_class.__call__)
            for decorator in endpoint_handler.decorators:
                if isinstance(decorator, partial):
                    my_class.__call__ = decorator()(my_class.__call__)
                else:
                    my_class.__call__ = decorator(my_class.__call__)

    def __repr__(self) -> str:
        return f"{super().__repr__()}\n(mapped to: {repr(self._original_func)})"

    def __call__(
        self,
        *path_params,
        quiet: bool = False,
        headers: dict[str, str] = None,
        stream: bool = None,
        with_hooks: bool = True,
        validate: bool = None,
        **params,
    ) -> RestResponse:
        """Make an API call to the endpoint

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param headers: Temporary headers to add to the request
        :param stream: Control the value of "stream" parameter passed to the underlying requests lib.
                       Explicitly passing True or False will override the value defined for an
                       API function definition (requests_lib_options), if there is any
        :param with_hooks: Invoke pre/post request hooks
        :param validate: Validate the request parameter in Pydantic strict mode
        :param params: Request body or query parameters
        """
        if validate is None:
            validate = pydantic_model_util.is_validation_mode()

        if self.endpoint.is_deprecated:
            logger.warning(f"DEPRECATED: '{self.endpoint}' is deprecated")

        # use the copy since we cache the request function
        requests_lib_options = deepcopy(self._requests_lib_options)
        if stream is not None:
            requests_lib_options.update(stream=stream)
        if headers is not None:
            requests_lib_options.update(headers=headers)
        if requests_lib_options.get("stream"):
            logger.info("stream=True was specified")

        # Fill path variables
        try:
            completed_path = endpoint_func_util.complete_endpoint(self.endpoint, path_params)
        except ValueError as e:
            msg = str(e)
            if api_spec_definition := self.get_usage():
                msg = f"{str(e)}\n{color(api_spec_definition, color_code=ColorCodes.YELLOW)}"
            raise ValueError(msg) from None

        # Check if parameters used are expected for the endpoint. If not, it is an indication that the API function is
        # not up-to-date.
        endpoint_func_util.check_params(self.endpoint, params)

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
        rest_func_params = endpoint_func_util.generate_rest_func_params(
            self.endpoint,
            params,
            self.rest_client.session.headers,
            quiet=quiet,
            use_query_string=self._use_query_string,
            is_validation_mode=validate,
            **requests_lib_options,
        )
        r = None
        request_exception = None
        try:
            rest_func = getattr(self.rest_client, f"_{self.method}")
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
            print(color(api_spec_definition, color_code=ColorCodes.YELLOW))
        else:
            print("Docs not available")

    def with_retry(
        self,
        *args,
        condition: int | Sequence[int] | Callable[[RestResponse], bool] = lambda r: not r.ok,
        num_retry: int = 1,
        retry_after: float = 5,
        **kwargs,
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

    def get_usage(self) -> Optional[str]:
        """Get OpenAPI spec definition for the endpoint"""
        if self.api_client and self.endpoint.is_documented:
            return self.api_client.api_spec.get_endpoint_usage(self.endpoint)
