from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Sequence
from contextlib import asynccontextmanager, contextmanager
from copy import copy
from functools import cache, partial, wraps
from typing import TYPE_CHECKING, Any, Concatenate, Generic, Literal, ParamSpec, Self, TypeVar, cast, overload

from common_libs.clients.rest_client import RestClient
from common_libs.clients.rest_client.utils import retry_on
from common_libs.job_executor import Job, run_concurrent
from common_libs.lock import Lock
from common_libs.logging import get_logger
from common_libs.naming import to_class_name
from httpx import HTTPError

from ..types import EndpointModel, RestResponse
from ..utils import endpoint_call as endpoint_call_util
from ..utils import endpoint_model as endpoint_model_util
from .executors import AsyncExecutor, SyncExecutor

if TYPE_CHECKING:
    from ..base import APIBase
    from ..base.api_client import APIClient
    from ..types import _ResponseList, _ResponseOrExceptionList, _ResponseStream
    from .endpoint_handler import EndpointHandler


P = ParamSpec("P")
# _T is intentionally unparameterized: bound="EndpointFunc[Any]" widens the class-scoped P to Any in the return type of
# requires_instance-decorated methods that return Callable[P, R], which breaks the propagation of P
_T = TypeVar("_T", bound="EndpointFunc")  # type: ignore[type-arg]
_P = ParamSpec("_P")
_R = TypeVar("_R")

_SAFE_HTTP_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

__all__ = ["AsyncEndpointFunc", "EndpointFunc", "SyncEndpointFunc"]

logger = get_logger(__name__)


def _as_response(f: Callable[_P, Awaitable[RestResponse]]) -> Callable[_P, RestResponse]:
    """Retype an async callable as a plain callable returning RestResponse.

    Applied to AsyncEndpointFunc.__call__ so that the SyncEndpointFunc | AsyncEndpointFunc union appears as a single
    non-coroutine callable type to the type checker.
    At runtime this is a no-op.
    """
    return cast(Callable[_P, RestResponse], f)


def _as_response_stream(f: Callable[_P, object]) -> Callable[_P, _ResponseStream]:
    """Retype a context-manager callable as returning the dual _ResponseStream.

    Applied to both SyncEndpointFunc.stream() and AsyncEndpointFunc.stream() so the
    SyncEndpointFunc | AsyncEndpointFunc union presents a single type that supports both `with` and `async with`.
    At runtime this is a no-op.
    """
    return cast(Callable[_P, "_ResponseStream"], f)


def requires_instance(f: Callable[Concatenate[_T, _P], _R]) -> Callable[Concatenate[_T, _P], _R]:
    @wraps(f)
    def wrapper(self: _T, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        if self._instance is None:
            func_name = self._original_func.__name__ if f.__name__ == "__call__" else f.__name__
            raise TypeError(f"You can not access {func_name}() directly through the {self._owner.__name__} class.")
        return f(self, *args, **kwargs)

    return wrapper


class EndpointFunc(Generic[P]):
    """Base class for Sync/Async Endpoint function classes"""

    executor: SyncExecutor[P] | AsyncExecutor[P] | None = None

    def __init__(self, endpoint_handler: EndpointHandler[P], instance: APIBase[Any] | None, owner: type[APIBase[Any]]):
        """Initialize endpoint function"""
        self.method = endpoint_handler.method
        self.path = endpoint_handler.path
        self.rest_client: RestClient | None
        self.api_client: APIClient | None
        if instance:
            self.api_client = instance.api_client
            self.rest_client = self.api_client.rest_client
        else:
            self.api_client = None
            self.rest_client = None

        # State used by _with_call_wrapper to compose with_xxx() wrappers in left-to-right (first=outermost) order
        self._call_wrappers: tuple[Callable[[Callable[..., Any]], Callable[..., Any]], ...] = ()
        self._base_call: Callable[..., Any] | None = None

        self._instance: APIBase[Any] | None = instance
        self._owner: type[APIBase[Any]] = owner
        self._original_func: Callable[..., RestResponse] = endpoint_handler.original_func
        self._use_query_string = endpoint_handler.use_query_string
        self._raw_options = endpoint_handler.default_raw_options

        self.endpoint = owner._endpoint_class(
            api_class=owner,
            method=self.method,
            path=self.path,
            func_name=self._original_func.__name__,
            model=self.model,
            url=f"{self.rest_client.base_url}{self.path}" if instance else None,
            content_type=endpoint_handler.content_type,
            is_public=endpoint_handler.is_public,
            is_documented=owner.is_documented and endpoint_handler.is_documented,
            is_deprecated=owner.is_deprecated or endpoint_handler.is_deprecated,
        )

        # Decorate the __call__ and stream() if wrappers are defined in the API class, or if decorators are
        # registered. If both request wrapper and endpoint decorators exist, endpoint decorators will be
        # processed first.
        #
        # A fresh per-instantiation subclass is created so wrappers are applied to an instance-private class
        # rather than to the shared cached class returned by _create().
        if instance:
            my_class = type(type(self).__name__, (type(self),), {})
            self.__class__ = my_class
            if request_wrappers := instance.request_wrapper():
                for request_wrapper in request_wrappers[::-1]:
                    my_class.__call__ = request_wrapper(my_class.__call__)  # type: ignore[method-assign]
            if stream_wrappers := instance.stream_wrapper():
                for stream_wrapper in stream_wrappers[::-1]:
                    my_class.stream = stream_wrapper(my_class.stream)  # type: ignore[attr-defined]
            for decorator in endpoint_handler.decorators:
                if isinstance(decorator, partial):
                    my_class.__call__ = decorator()(my_class.__call__)  # type: ignore[method-assign]
                else:
                    my_class.__call__ = decorator(my_class.__call__)  # type: ignore[method-assign]
            # Snapshot the fully-decorated __call__ as the base that with_xxx() wrappers compose around
            self._base_call = my_class.__call__

    def __repr__(self) -> str:
        return f"{super().__repr__()}\n(mapped to: {self._original_func!r})"

    @requires_instance
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        """Make an API call to the endpoint. This logic is commonly used for sync/acync API calls"""
        return await self._call(*args, **kwargs)  # type: ignore[arg-type]

    async def _call(
        self,
        *args: Any,
        quiet: bool = False,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> RestResponse:
        """Make an API call to the endpoint. This logic is commonly used for sync/async API calls

        Parameters can be passed either positionally or as keyword arguments. Path parameters are identified by
        matching their names against the `{placeholder}` tokens in the endpoint path. All remaining parameters are
        treated as body or query parameters.

        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param quiet: A flag to suppress API request/response log
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        path_params_dict, body_or_query_params = endpoint_call_util.split_params(
            self.path, self._original_func, args, kwargs
        )
        path_params = tuple(
            path_params_dict[ph] for ph in endpoint_call_util.get_path_placeholders(self.path) if ph in path_params_dict
        )

        path = endpoint_call_util.validate_path_and_params(
            self, *path_params, raw_options=raw_options, **body_or_query_params
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
            call_kwargs: dict[str, Any] = {}
            if raw_options:
                call_kwargs.update(raw_options=raw_options)
            if quiet:
                call_kwargs.update(quiet=quiet)
            r = await self._call_original_func(args, kwargs, call_kwargs)
            if r is not None:
                if not isinstance(r, RestResponse):
                    raise RuntimeError(f"Custom endpoint must return a RestResponse object, got {type(r).__name__}")
            else:
                sig_defaults = endpoint_call_util.get_signature_defaults(self._original_func, self.path)
                params = endpoint_call_util.generate_rest_func_params(
                    self.endpoint,
                    {**sig_defaults, **body_or_query_params},
                    self.rest_client.client.headers,
                    quiet=quiet,
                    use_query_string=self._use_query_string,
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
            self._run_post_hook(r, exception, with_hooks, path_params, body_or_query_params)

    @property
    def model(self) -> type[EndpointModel]:
        """Return the dynamically created model of the endpoint"""
        return endpoint_model_util.create_endpoint_model(self)

    def help(self) -> None:
        """Display the API function definition"""
        help(self._original_func)

    @requires_instance
    def with_retry(
        self,
        condition: int
        | type[Exception]
        | Sequence[int]
        | Sequence[type[Exception]]
        | Callable[[RestResponse | Exception], bool] = lambda r: not r.ok,
        num_retries: int = 1,
        retry_after: float | int | Callable[[RestResponse | Exception], float | int] = 5,
        safe_methods_only: bool = False,
    ) -> Self:
        """Return a configured, chainable endpoint func that retries on the given condition.

        Call the returned callable with the endpoint's own parameters, or chain with other with_xxx() wrappers before
        the final call.

        :param condition: Either status code(s), a callable that takes the response object, or an exception class
                          (or tuple of exception classes) to retry on when raised
        :param num_retries: The max number of retries
        :param retry_after: A short wait time in seconds before a retry
        :param safe_methods_only: Only retry for safe HTTP methods (GET, HEAD, OPTIONS)
        """

        def call_with_retry(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                return retry_on(
                    condition,
                    num_retries=num_retries,
                    retry_after=retry_after,
                    safe_methods_only=safe_methods_only,
                    _async_mode=self.api_client.async_mode,
                )(f)(*args, **kwargs)

            return wrapper

        return self._with_call_wrapper(call_with_retry)

    @requires_instance
    def with_lock(self, lock_name: str | None = None) -> Self:
        """Return a configured, chainable endpoint func that holds a distributed lock during the call.

        The lock is applied at the API endpoint function level, which means any other API calls in the same/other
        processes using the same API function will wait until the lock is acquired.

        Call the returned callable with the endpoint's own parameters, or chain with other with_xxx() wrappers before
        the final call.

        :param lock_name: Explicitly specify the lock name. Use this when the same lock needs to be
                          shared among multiple endpoints. Defaults to
                          '{app_name}-{APIClass}.{func_name}'.
        """
        if not lock_name:
            lock_name = f"{self._instance.app_name}-{type(self._instance).__name__}.{self._original_func.__name__}"

        def call_with_lock(f: Callable[..., Any]) -> Callable[..., Any]:
            if self.api_client.async_mode:

                @wraps(f)
                async def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    with Lock(lock_name):
                        return await f(*args, **kwargs)
            else:

                @wraps(f)
                def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    with Lock(lock_name):
                        return f(*args, **kwargs)

            return wrapper

        return self._with_call_wrapper(call_with_lock)

    @requires_instance
    def with_expected_status(self, *status_codes: int) -> Self:
        """Return a configured, chainable endpoint func that asserts the response status code.

        Raises AssertionError if the response status code is not one of the expected codes.

        Call the returned callable with the endpoint's own parameters, or chain with other with_xxx() wrappers before
        the final call.

        :param status_codes: One or more acceptable HTTP status codes
        """
        if not status_codes:
            raise ValueError("At least one expected status code must be given")

        def call_with_expected_status(f: Callable[..., Any]) -> Callable[..., Any]:
            def check(r: RestResponse) -> RestResponse:
                if r.status_code not in status_codes:
                    expected = "/".join(str(s) for s in status_codes)
                    raise AssertionError(f"Expected status code {expected}, but got {r.status_code}")
                return r

            if self.api_client.async_mode:

                @wraps(f)
                async def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    return check(await f(*args, **kwargs))

            else:

                @wraps(f)
                def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    return check(f(*args, **kwargs))

            return wrapper

        return self._with_call_wrapper(call_with_expected_status)

    @requires_instance
    def with_max_response_time(self, threshold_msecs: float | int) -> Self:
        """Return a configured, chainable endpoint func that asserts the response time.

        Raises AssertionError if the server response time exceeds threshold_msecs.

        Call the returned callable with the endpoint's own parameters, or chain with other with_xxx() wrappers before
        the final call.

        :param threshold_msecs: The maximum acceptable response time in milliseconds
        """

        def call_with_max_response_time(f: Callable[..., Any]) -> Callable[..., Any]:
            def check(r: RestResponse) -> RestResponse:
                if r.response_time * 1000 > threshold_msecs:
                    raise AssertionError(
                        f"Response time {int(r.response_time * 1000)} msecs exceeded the threshold of "
                        f"{threshold_msecs} msecs"
                    )
                return r

            if self.api_client.async_mode:

                @wraps(f)
                async def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    return check(await f(*args, **kwargs))

            else:

                @wraps(f)
                def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    return check(f(*args, **kwargs))

            return wrapper

        return self._with_call_wrapper(call_with_max_response_time)

    @requires_instance
    def with_polling(
        self,
        until: Callable[[RestResponse], bool],
        interval: float | int = 5,
        timeout: float | int = 60,
    ) -> Self:
        """Return a configured, chainable endpoint func that polls until a condition is met.

        Repeatedly calls the endpoint until until(response) returns True, waiting interval seconds between calls.
        Raises TimeoutError if the condition is not met within timeout seconds. Unlike with_retry
        (which retries on failure), this polls successful responses — e.g. for eventual consistency or async job
        completion. The endpoint is always called at least once.

        Call the returned callable with the endpoint's own parameters, or chain with other with_xxx() wrappers before
        the final call.

        :param until: A callable taking the response object that returns True when polling should stop
        :param interval: Wait time in seconds between polls
        :param timeout: Maximum total time in seconds to keep polling before raising TimeoutError
        """

        def call_with_polling(f: Callable[..., Any]) -> Callable[..., Any]:
            msg = f"Polling condition was not met within {timeout} seconds"
            if self.api_client.async_mode:

                @wraps(f)
                async def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    deadline = time.monotonic() + timeout
                    while True:
                        r = await f(*args, **kwargs)
                        if until(r):
                            return r
                        if time.monotonic() + interval >= deadline:
                            raise TimeoutError(msg)
                        await asyncio.sleep(interval)

            else:

                @wraps(f)
                def wrapper(*args: Any, **kwargs: Any) -> RestResponse:
                    deadline = time.monotonic() + timeout
                    while True:
                        r = f(*args, **kwargs)
                        if until(r):
                            return r
                        if time.monotonic() + interval >= deadline:
                            raise TimeoutError(msg)
                        time.sleep(interval)

            return wrapper

        return self._with_call_wrapper(call_with_polling)

    @staticmethod
    @cache
    def _create(
        api_class: type[APIBase[Any]], orig_func: Callable[..., Any], async_mode: bool
    ) -> type[SyncEndpointFunc[Any]] | type[AsyncEndpointFunc[Any]]:
        """Dynamically create an EndpointFunc class for the given endpoint function"""
        base_class = api_class._async_endpoint_func_class if async_mode else api_class._sync_endpoint_func_class
        class_name = f"{api_class.__name__}{to_class_name(orig_func.__name__, suffix=EndpointFunc.__name__)}"
        return cast(type[SyncEndpointFunc[Any]] | type[AsyncEndpointFunc[Any]], type(class_name, (base_class,), {}))

    def _prepare_stream_request(
        self,
        path_params: tuple[Any, ...],
        quiet: bool,
        with_hooks: bool | None,
        raw_options: dict[str, Any] | None,
        body_or_query_params: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Validate params, run pre-request hook, generate REST params for streaming.

        Returns (path, params) tuple.
        """
        path = endpoint_call_util.validate_path_and_params(
            self, *path_params, raw_options=raw_options, **body_or_query_params
        )
        if with_hooks:
            self._instance.pre_request_hook(self.endpoint, *path_params, **body_or_query_params)
        sig_defaults = endpoint_call_util.get_signature_defaults(self._original_func, self.path)
        params = endpoint_call_util.generate_rest_func_params(
            self.endpoint,
            {**sig_defaults, **body_or_query_params},
            self.rest_client.client.headers,
            quiet=quiet,
            use_query_string=self._use_query_string,
            **self._raw_options | (raw_options or {}),
        )
        return path, params

    def _run_post_hook(
        self,
        r: RestResponse | None,
        exception: Exception | None,
        with_hooks: bool | None,
        path_params: tuple[Any, ...],
        body_or_query_params: dict[str, Any],
    ) -> None:
        """Run post-request hook with standard error handling."""
        if with_hooks:
            try:
                self._instance.post_request_hook(self.endpoint, r, exception, *path_params, **body_or_query_params)
            except AssertionError:
                raise
            except Exception as e:
                logger.exception(e)

    async def _call_original_func(
        self, func_args: tuple[Any, ...], func_kwargs: dict[str, Any], kwargs: dict[str, Any]
    ) -> RestResponse | None:
        """Call the user-defined original endpoint function with the original args/kwargs.

        :param func_args: Positional arguments as received by __call__
        :param func_kwargs: Keyword arguments as received by __call__
        :param kwargs: Extra kwargs for the original func when explicitly set
        """
        r = self._original_func(self._instance, *func_args, **{**func_kwargs, **kwargs})
        if self.api_client.async_mode and asyncio.iscoroutine(r):
            # The original function is not an async function but rest_client used inside the original function is
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

    def _with_call_wrapper(self, wrapper: Callable[[Callable[..., Any]], Callable[..., Any]]) -> Self:
        _self = copy(self)
        _self._call_wrappers = (*_self._call_wrappers, wrapper)
        _cls = type(type(_self).__name__, (type(_self),), {})
        # Rebuild the composition from the base each time so the first with_xxx() in the chain
        # becomes the outermost layer (intuitive left-to-right reading).
        assert _self._base_call is not None  # always set for instance-bound funcs; with_xxx() requires an instance
        call = _self._base_call
        for wrapper in reversed(_self._call_wrappers):
            call = wrapper(call)
        _cls.__call__ = call  # type: ignore[method-assign]
        _self.__class__ = _cls
        return _self


class SyncEndpointFunc(EndpointFunc[P]):
    """Endpoint function class (Sync)

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

    executor = SyncExecutor()

    @requires_instance
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        """Make a sync API call to the endpoint"""
        return asyncio.run(super().__call__(*args, **kwargs))

    @_as_response_stream
    @contextmanager
    @requires_instance
    def stream(self, *args: P.args, **kwargs: P.kwargs) -> Generator[RestResponse]:
        """Stream the response

        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        with self._stream(*args, **kwargs) as r:  # type: ignore[arg-type]
            yield r

    @overload
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: Literal[False] = ...
    ) -> Callable[P, _ResponseList]: ...
    @overload
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: Literal[True]
    ) -> Callable[P, _ResponseOrExceptionList]: ...
    @requires_instance
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: bool = False
    ) -> Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]:
        """Return a callable that concurrently makes duplicated API calls to the endpoint.

        Call the returned callable with the endpoint's own parameters.

        :param num: Number of concurrent API calls
        :param return_exceptions: If True, exceptions raised during calls are collected and included in the returned
                                  list instead of being propagated
        """

        def call_with_concurrency(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> list[RestResponse]:
                return run_concurrent([Job(f, args, kwargs) for _ in range(num)], return_exceptions=return_exceptions)

            return wrapper

        return cast(
            "Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]",
            self._with_call_wrapper(call_with_concurrency),
        )

    @overload
    def with_repeat(self, num: int = 2, *, return_exceptions: Literal[False] = ...) -> Callable[P, _ResponseList]: ...
    @overload
    def with_repeat(
        self, num: int = 2, *, return_exceptions: Literal[True]
    ) -> Callable[P, _ResponseOrExceptionList]: ...
    @requires_instance
    def with_repeat(
        self, num: int = 2, *, return_exceptions: bool = False
    ) -> Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]:
        """Return a callable that sequentially makes duplicated API calls to the endpoint.

        Call the returned callable with the endpoint's own parameters. The endpoint is called num times sequentially.
        When return_exceptions=True, exceptions are collected in the returned list instead of being propagated —
        so all num calls run even when some fail (KeyboardInterrupt/SystemExit still propagate).
        Returns the results in call order. This is terminal and must always be the last wrapper in a chain.

        :param num: Number of sequential API calls
        :param return_exceptions: If True, exceptions raised during calls are collected and included in the returned
                                  list instead of being propagated.
        """

        def call_with_repeat(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> list[RestResponse] | list[RestResponse | Exception]:
                if return_exceptions:
                    results: list[RestResponse | Exception] = []
                    for _ in range(num):
                        try:
                            results.append(f(*args, **kwargs))
                        except Exception as e:
                            results.append(e)
                    return results
                return [f(*args, **kwargs) for _ in range(num)]

            return wrapper

        return cast(
            "Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]",
            self._with_call_wrapper(call_with_repeat),
        )

    @contextmanager
    def _stream(
        self,
        *args: Any,
        quiet: bool = False,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Generator[RestResponse]:
        """Stream the response (implementation)

        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param quiet: A flag to suppress API request/response log
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        path_params_dict, body_or_query_params = endpoint_call_util.split_params(
            self.path, self._original_func, args, kwargs
        )
        path_params = tuple(
            path_params_dict[ph] for ph in endpoint_call_util.get_path_placeholders(self.path) if ph in path_params_dict
        )
        path, params = self._prepare_stream_request(path_params, quiet, with_hooks, raw_options, body_or_query_params)
        r = None
        exception = None
        try:
            with self.executor.execute_stream(self, path, params) as r:
                yield r
        except HTTPError as e:
            exception = e
            raise
        except (Exception, KeyboardInterrupt):
            with_hooks = False
            raise
        finally:
            self._run_post_hook(r, exception, with_hooks, path_params, body_or_query_params)


class AsyncEndpointFunc(EndpointFunc[P]):
    """Endpoint function class (Async)

    All parameters passed to the original API class function call will be passed through to the __call__()
    """

    executor = AsyncExecutor()

    @_as_response
    @requires_instance
    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        """Make an async API call to the endpoint"""
        return await super().__call__(*args, **kwargs)

    @_as_response_stream
    @asynccontextmanager
    @requires_instance
    async def stream(self, *args: P.args, **kwargs: P.kwargs) -> AsyncGenerator[RestResponse]:
        """Stream response from an API call to the endpoint

        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        async with self._stream(*args, **kwargs) as r:  # type: ignore[arg-type]
            yield r

    @overload
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: Literal[False] = ...
    ) -> Callable[P, _ResponseList]: ...
    @overload
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: Literal[True]
    ) -> Callable[P, _ResponseOrExceptionList]: ...
    @requires_instance
    def with_concurrency(
        self, num: int = 2, *, return_exceptions: bool = False
    ) -> Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]:
        """Return a coroutine callable that concurrently makes duplicated API calls to the endpoint.

        Call the returned callable with the endpoint's own parameters.

        :param num: Number of concurrent API calls
        :param return_exceptions: If True, exceptions raised during calls are collected and included in the returned
                                  list instead of being propagated.
        """

        def call_with_concurrency(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            async def wrapper(*args: Any, **kwargs: Any) -> list[RestResponse] | list[RestResponse | Exception]:
                if return_exceptions:

                    async def safe_f(*a: Any, **kw: Any) -> RestResponse | Exception:
                        try:
                            return await f(*a, **kw)
                        except Exception as e:
                            return e

                    target: Callable[..., Any] = safe_f
                else:
                    target = f
                async with asyncio.TaskGroup() as tg:
                    tasks = [tg.create_task(target(*args, **kwargs)) for _ in range(num)]
                return [t.result() for t in tasks]

            return wrapper

        return cast(
            "Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]",
            self._with_call_wrapper(call_with_concurrency),
        )

    @overload
    def with_repeat(self, num: int = 2, *, return_exceptions: Literal[False] = ...) -> Callable[P, _ResponseList]: ...
    @overload
    def with_repeat(
        self, num: int = 2, *, return_exceptions: Literal[True]
    ) -> Callable[P, _ResponseOrExceptionList]: ...
    @requires_instance
    def with_repeat(
        self, num: int = 2, *, return_exceptions: bool = False
    ) -> Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]:
        """Return a coroutine callable that sequentially makes duplicated API calls to the endpoint.

        Call the returned callable with the endpoint's own parameters. The endpoint is called num times sequentially.
        When return_exceptions=True, exceptions are collected in the returned list instead of being propagated —
        so all num calls run even when some fail (KeyboardInterrupt/SystemExit/CancelledError still propagate).
        Returns the results in call order. This is terminal and must always be the last wrapper in a chain.

        :param num: Number of sequential API calls
        :param return_exceptions: If True, exceptions raised during calls are collected and included in the returned
                                  list instead of being propagated.
        """

        def call_with_repeat(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            async def wrapper(*args: Any, **kwargs: Any) -> list[RestResponse] | list[RestResponse | Exception]:
                if return_exceptions:
                    results: list[RestResponse | Exception] = []
                    for _ in range(num):
                        try:
                            results.append(await f(*args, **kwargs))
                        except Exception as e:
                            results.append(e)
                    return results
                return [await f(*args, **kwargs) for _ in range(num)]

            return wrapper

        return cast(
            "Callable[P, _ResponseList] | Callable[P, _ResponseOrExceptionList]",
            self._with_call_wrapper(call_with_repeat),
        )

    @asynccontextmanager
    async def _stream(
        self,
        *args: Any,
        quiet: bool = False,
        with_hooks: bool | None = True,
        raw_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[RestResponse]:
        """Stream response from an API call to the endpoint (implementation)

        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param quiet: A flag to suppress API request/response log
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        path_params_dict, body_or_query_params = endpoint_call_util.split_params(
            self.path, self._original_func, args, kwargs
        )
        path_params = tuple(
            path_params_dict[ph] for ph in endpoint_call_util.get_path_placeholders(self.path) if ph in path_params_dict
        )
        path, params = self._prepare_stream_request(path_params, quiet, with_hooks, raw_options, body_or_query_params)
        r = None
        exception = None
        try:
            async with self.executor.execute_stream(self, path, params) as r:
                yield r
        except HTTPError as e:
            exception = e
            raise
        except (Exception, KeyboardInterrupt):
            with_hooks = False
            raise
        finally:
            self._run_post_hook(r, exception, with_hooks, path_params, body_or_query_params)
