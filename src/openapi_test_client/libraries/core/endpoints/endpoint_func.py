from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from functools import cache, wraps
from typing import TYPE_CHECKING, Any, ParamSpec, TypeAlias, TypeVar, Union, cast

from common_libs.ansi_colors import ColorCodes, color
from common_libs.clients.rest_client import APIResponse, RestClient, RestResponse
from common_libs.clients.rest_client.utils import retry_on
from common_libs.job_executor import Job, run_concurrent
from common_libs.lock import Lock
from common_libs.logging import get_logger
from httpx import HTTPError

import openapi_test_client.libraries.core.endpoints.utils.endpoint_call as endpoint_call_util
import openapi_test_client.libraries.core.endpoints.utils.endpoint_model as endpoint_model_util
import openapi_test_client.libraries.core.endpoints.utils.pydantic_model as pydantic_model_util
from openapi_test_client.libraries.common.misc import generate_class_name
from openapi_test_client.libraries.core.api_classes import APIBase
from openapi_test_client.libraries.core.endpoints.executors import AsyncExecutor, SyncExecutor
from openapi_test_client.libraries.core.types import EndpointModel

if TYPE_CHECKING:
    from openapi_test_client.clients.openapi import OpenAPIClient
    from openapi_test_client.libraries.core.endpoints.endpoint import Endpoint
    from openapi_test_client.libraries.core.endpoints.endpoint_handler import EndpointHandler


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

__all__ = ["AsyncEndpointFunc", "EndpointFunc", "SyncEndpointFunc"]


logger = get_logger(__name__)


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
        from openapi_test_client.libraries.core.endpoints.endpoint import Endpoint

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
                from functools import partial

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
        path = endpoint_call_util.validate_path_and_params(
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
                params = endpoint_call_util.generate_rest_func_params(
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
        path = endpoint_call_util.validate_path_and_params(
            self, *path_params, validate=validate, raw_options=raw_options, **body_or_query_params
        )

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)

        # Make a request
        r = None
        exception = None
        try:
            params = endpoint_call_util.generate_rest_func_params(
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
        path = endpoint_call_util.validate_path_and_params(
            self, *path_params, validate=validate, raw_options=raw_options, **body_or_query_params
        )

        # pre-request hook
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)

        # Make a request
        r = None
        exception = None
        try:
            params = endpoint_call_util.generate_rest_func_params(
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
        except (Exception, KeyboardInterrupt):
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
