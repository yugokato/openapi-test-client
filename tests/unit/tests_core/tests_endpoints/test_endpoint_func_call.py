"""Unit tests for endpoints_func.py (func calls)"""

import re
from collections.abc import Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Any, NoReturn
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import RequestExt, ResponseExt
from common_libs.clients.rest_client.utils import set_request_to_exception
from common_libs.lock import Lock
from filelock import Timeout as FileLockTimeout
from httpx import AsyncClient, Client, ConnectError, HTTPError, Request
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.endpoints.endpoint_func as _endpoint_func_module
import openapi_test_client.libraries.core.utils.endpoint_call as endpoint_call_util
from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.core.endpoints import (
    AsyncEndpointFunc,
    Stats,
    SyncEndpointFunc,
    endpoint,
)
from openapi_test_client.libraries.core.endpoints.executors import AsyncExecutor, SyncExecutor
from openapi_test_client.libraries.core.endpoints.stats import StatsCollector
from openapi_test_client.libraries.core.types import Unset

pytestmark = [pytest.mark.unittest]


class TestSyncEndpointFuncCall:
    """Tests for SyncEndpointFunc.__call__ sync execution path"""

    def test_sync_call_returns_rest_response(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that SyncEndpointFunc.__call__ returns a RestResponse"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        r = instance.get_something()
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()

    def test_sync_call_uses_sync_executor(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that SyncEndpointFunc uses SyncExecutor to execute the HTTP request"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        endpoint_func = instance.get_something
        assert isinstance(endpoint_func, SyncEndpointFunc)
        assert isinstance(endpoint_func.executor, SyncExecutor)

        instance.get_something()
        mock_httpx_request.assert_called_once()

    def test_sync_call_invokes_pre_and_post_hooks(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that pre_request_hook and post_request_hook are called during sync execution"""
        call_stack: list[str] = []

        def mock_httpx_side_effect(*args: Any, **kwargs: Any) -> ResponseExt:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(Client, "request", side_effect=mock_httpx_side_effect)

        class HookedAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("pre")

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("post")

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client)
        instance.get_something()

        assert call_stack == ["pre", "call", "post"]

    @pytest.mark.parametrize("with_hooks", [True, False])
    def test_sync_call_flow_with_decorators_and_wrappers(
        self, mocker: MockerFixture, api_client: APIClient, with_hooks: bool
    ) -> None:
        """Test that endpoint decorators and request wrappers fire in correct order in sync mode"""
        call_stack: list[str] = []

        def mock_httpx_side_effect(*args: Any, **kwargs: Any) -> ResponseExt:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(Client, "request", side_effect=mock_httpx_side_effect)

        @endpoint.decorator
        def deco1(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_stack.append("deco1_before")
                result = f(*args, **kwargs)
                call_stack.append("deco1_after")
                return result

            return wrapper

        @endpoint.decorator
        def deco2(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_stack.append("deco2_before")
                result = f(*args, **kwargs)
                call_stack.append("deco2_after")
                return result

            return wrapper

        class SyncHookedAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("pre_request")

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("post_request")

            def request_wrapper(self) -> list[Callable[..., Any]]:
                def request_wrapper1(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    def inner(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper1_before")
                        result = f(*args, **kwargs)
                        call_stack.append("request_wrapper1_after")
                        return result

                    return inner

                def request_wrapper2(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    def inner(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper2_before")
                        result = f(*args, **kwargs)
                        call_stack.append("request_wrapper2_after")
                        return result

                    return inner

                return [request_wrapper1, request_wrapper2]

            @deco1
            @deco2
            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = SyncHookedAPI(api_client)
        assert call_stack == []
        instance.get_something(with_hooks=with_hooks)

        if with_hooks:
            assert call_stack == [
                "deco1_before",
                "deco2_before",
                "request_wrapper1_before",
                "request_wrapper2_before",
                "pre_request",
                "call",
                "post_request",
                "request_wrapper2_after",
                "request_wrapper1_after",
                "deco2_after",
                "deco1_after",
            ]
        else:
            assert call_stack == [
                "deco1_before",
                "deco2_before",
                "request_wrapper1_before",
                "request_wrapper2_before",
                "call",
                "request_wrapper2_after",
                "request_wrapper1_after",
                "deco2_after",
                "deco1_after",
            ]

    def test_sync_call_with_custom_body_returning_rest_response(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that a custom sync endpoint body returning RestResponse bypasses auto-generated request path"""
        mocker.patch.object(Client, "request")
        f = endpoint_call_util.generate_rest_func_params
        spy_generate = mocker.patch(f"{f.__module__}.{f.__name__}")

        class SyncCustomAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return self.api_client.rest_client._get("/v1/something")

        instance = SyncCustomAPI(api_client)
        r = instance.get_something()

        assert isinstance(r, RestResponse)
        spy_generate.assert_not_called()

    def test_sync_call_with_custom_body_wrong_return_type(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a custom sync endpoint body returning a non-RestResponse raises RuntimeError"""
        mocker.patch.object(Client, "request")

        class SyncBadReturnAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return "not a response"

        instance = SyncBadReturnAPI(api_client)
        with pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object, got str"):
            instance.get_something()

    def test_sync_call_http_error_propagates(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that HTTPError raised during sync execution propagates to the caller"""
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("connection error")
        connect_error.request = mock_request
        mocker.patch.object(Client, "request", side_effect=connect_error)
        instance = api_class(api_client)
        with pytest.raises(HTTPError, match="connection error"):
            instance.get_something()

    def test_sync_call_http_error_still_runs_post_hook(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that post_request_hook is still called even when an HTTPError occurs in sync mode"""
        post_hook_called = False
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("timeout")
        connect_error.request = mock_request

        mocker.patch.object(Client, "request", side_effect=connect_error)

        class HookedAPI(APIBase):
            app_name = api_client.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_hook_called
                post_hook_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client)
        with pytest.raises(HTTPError):
            instance.get_something()

        assert post_hook_called is True

    def test_sync_with_concurrency_makes_multiple_calls(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_concurrency in sync mode issues N concurrent HTTP requests"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, SyncEndpointFunc)

        results = endpoint_func.with_concurrency(num=3)()
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert mock_httpx_request.call_count == 3

    def test_sync_with_concurrency_collects_exceptions_with_return_exceptions(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_concurrency(return_exceptions=True) collects all exceptions instead of propagating"""
        mocker.patch.object(Client, "request", side_effect=ValueError("always fails"))
        instance = api_class(api_client)

        results = instance.get_something.with_concurrency(num=3, return_exceptions=True)()

        assert len(results) == 3
        assert all(isinstance(r, ValueError) for r in results)
        assert Client.request.call_count == 3

    def test_sync_call_uses_endpoint_path(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that the sync endpoint call uses the configured endpoint path"""
        mock_httpx_request = mocker.patch.object(Client, "request")

        class PathAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/items")
            def get_items(self) -> RestResponse: ...

        instance = PathAPI(api_client)
        instance.get_items()

        call_args = mock_httpx_request.call_args
        assert call_args.args == ("GET", "/v1/items")


class TestAsyncEndpointFuncCall:
    """Tests for AsyncEndpointFunc.__call__ async execution path"""

    async def test_async_call_returns_rest_response(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that AsyncEndpointFunc.__call__ returns a RestResponse when awaited"""
        mocker.patch.object(AsyncClient, "request")
        instance = api_class_async(api_client_async)
        r = await instance.get_something()
        assert isinstance(r, RestResponse)

    async def test_async_call_uses_async_executor(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that AsyncEndpointFunc uses AsyncExecutor to execute the HTTP request"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")
        instance = api_class_async(api_client_async)
        endpoint_func = instance.get_something
        assert isinstance(endpoint_func, AsyncEndpointFunc)
        assert isinstance(endpoint_func.executor, AsyncExecutor)

        await instance.get_something()
        mock_httpx_request.assert_called_once()

    async def test_async_call_invokes_pre_and_post_hooks(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that pre_request_hook and post_request_hook are called during async execution"""
        call_stack: list[str] = []

        def mock_httpx_side_effect(*args: Any, **kwargs: Any) -> ResponseExt:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(AsyncClient, "request", side_effect=mock_httpx_side_effect)

        class HookedAPI(APIBase):
            app_name = api_client_async.app_name

            def pre_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("pre")

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("post")

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client_async)
        await instance.get_something()

        assert call_stack == ["pre", "call", "post"]

    @pytest.mark.parametrize("with_hooks", [True, False])
    async def test_async_call_flow_with_decorators_and_wrappers(
        self, mocker: MockerFixture, api_client_async: APIClient, with_hooks: bool
    ) -> None:
        """Test that endpoint decorators and request wrappers fire in correct order in async mode"""
        call_stack: list[str] = []

        def mock_httpx_side_effect(*args: Any, **kwargs: Any) -> ResponseExt:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(AsyncClient, "request", side_effect=mock_httpx_side_effect)

        @endpoint.decorator
        def deco1(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_stack.append("deco1_before")
                result = await f(*args, **kwargs)
                call_stack.append("deco1_after")
                return result

            return wrapper

        @endpoint.decorator
        def deco2(f: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(f)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                call_stack.append("deco2_before")
                result = await f(*args, **kwargs)
                call_stack.append("deco2_after")
                return result

            return wrapper

        class AsyncHookedAPI(APIBase):
            app_name = api_client_async.app_name

            def pre_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("pre_request")

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("post_request")

            def request_wrapper(self) -> list[Callable[..., Any]]:
                def request_wrapper1(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    async def inner(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper1_before")
                        result = await f(*args, **kwargs)
                        call_stack.append("request_wrapper1_after")
                        return result

                    return inner

                def request_wrapper2(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    async def inner(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper2_before")
                        result = await f(*args, **kwargs)
                        call_stack.append("request_wrapper2_after")
                        return result

                    return inner

                return [request_wrapper1, request_wrapper2]

            @deco1
            @deco2
            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = AsyncHookedAPI(api_client_async)
        assert call_stack == []
        await instance.get_something(with_hooks=with_hooks)

        if with_hooks:
            assert call_stack == [
                "deco1_before",
                "deco2_before",
                "request_wrapper1_before",
                "request_wrapper2_before",
                "pre_request",
                "call",
                "post_request",
                "request_wrapper2_after",
                "request_wrapper1_after",
                "deco2_after",
                "deco1_after",
            ]
        else:
            assert call_stack == [
                "deco1_before",
                "deco2_before",
                "request_wrapper1_before",
                "request_wrapper2_before",
                "call",
                "request_wrapper2_after",
                "request_wrapper1_after",
                "deco2_after",
                "deco1_after",
            ]

    async def test_async_call_with_custom_body_returning_rest_response(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that a custom async endpoint body returning RestResponse bypasses auto-generated request path"""
        mocker.patch.object(AsyncClient, "request")
        f = endpoint_call_util.generate_rest_func_params
        spy_generate = mocker.patch(f"{f.__module__}.{f.__name__}")

        class AsyncCustomAPI(APIBase):
            app_name = api_client_async.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return self.api_client.rest_client._get("/v1/something")

        instance = AsyncCustomAPI(api_client_async)
        r = await instance.get_something()

        assert isinstance(r, RestResponse)
        spy_generate.assert_not_called()

    async def test_async_call_with_custom_body_wrong_return_type(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that a custom async endpoint body returning non-RestResponse raises RuntimeError"""
        mocker.patch.object(AsyncClient, "request")

        class AsyncBadReturnAPI(APIBase):
            app_name = api_client_async.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return "not a response"

        instance = AsyncBadReturnAPI(api_client_async)
        with pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object, got str"):
            await instance.get_something()

    async def test_async_call_http_error_propagates(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that HTTPError raised during async execution propagates to the caller"""
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("connection error")
        connect_error.request = mock_request
        mocker.patch.object(AsyncClient, "request", side_effect=connect_error)
        instance = api_class_async(api_client_async)
        with pytest.raises(HTTPError, match="connection error"):
            await instance.get_something()

    async def test_async_call_http_error_still_runs_post_hook(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that post_request_hook is still called even when an HTTPError occurs in async mode"""
        post_hook_called = False
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("timeout")
        connect_error.request = mock_request

        mocker.patch.object(AsyncClient, "request", side_effect=connect_error)

        class HookedAPI(APIBase):
            app_name = api_client_async.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_hook_called
                post_hook_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client_async)
        with pytest.raises(HTTPError):
            await instance.get_something()

        assert post_hook_called is True

    async def test_async_with_concurrency_makes_multiple_calls(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that with_concurrency in async mode issues N concurrent HTTP requests via TaskGroup"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")
        instance = api_class_async(api_client_async)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, AsyncEndpointFunc)

        results = await endpoint_func.with_concurrency(num=3)()
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert mock_httpx_request.call_count == 3

    async def test_async_with_concurrency_collects_exceptions_with_return_exceptions(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_concurrency(return_exceptions=True) collects all exceptions instead of propagating"""
        mocker.patch.object(AsyncClient, "request", side_effect=ValueError("always fails"))
        instance = api_class_async(api_client_async)

        results = await instance.get_something.with_concurrency(num=3, return_exceptions=True)()

        assert len(results) == 3
        assert all(isinstance(r, ValueError) for r in results)
        assert AsyncClient.request.call_count == 3

    async def test_async_call_uses_endpoint_path(self, mocker: MockerFixture, api_client_async: APIClient) -> None:
        """Test that the async endpoint call uses the configured endpoint path"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")

        class PathAPI(APIBase):
            app_name = api_client_async.app_name

            @endpoint.get("/v1/items")
            def get_items(self) -> RestResponse: ...

        instance = PathAPI(api_client_async)
        await instance.get_items()

        call_args = mock_httpx_request.call_args
        assert call_args.args == ("GET", "/v1/items")


class TestSyncEndpointFuncStreamCall:
    """Tests for SyncEndpointFunc.stream()"""

    def test_sync_stream_yields_rest_response(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that stream() context manager yields a RestResponse"""
        mock_resp = _make_stream_response()

        @contextmanager
        def fake_execute_stream(self_executor: SyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(SyncExecutor, "execute_stream", new=fake_execute_stream)
        instance = api_class(api_client)
        with instance.get_something.stream() as r:
            assert r is mock_resp

    def test_sync_stream_http_error_propagates(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that an HTTPError raised inside stream() propagates to the caller"""
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("stream connection failed")
        connect_error.request = mock_request

        class _RaisingCM:
            def __enter__(self) -> Any:
                raise connect_error

            def __exit__(self, *args: Any) -> None:
                pass

        mocker.patch.object(SyncExecutor, "execute_stream", return_value=_RaisingCM())
        instance = api_class(api_client)
        with pytest.raises(HTTPError, match="stream connection failed"):
            with instance.get_something.stream():
                pass

    def test_sync_stream_post_hook_called_after_success(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that post_request_hook is called after a successful stream"""
        post_called = False
        mock_resp = _make_stream_response()

        @contextmanager
        def fake_execute_stream(self_executor: SyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(SyncExecutor, "execute_stream", new=fake_execute_stream)

        class HookedAPI(APIBase):
            app_name = api_client.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_called
                post_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client)
        with instance.get_something.stream():
            pass

        assert post_called is True

    def test_sync_stream_post_hook_skipped_on_non_http_exception(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that post_request_hook is skipped when a non-HTTPError exception is raised inside stream()"""
        post_called = False
        mock_resp = _make_stream_response()

        @contextmanager
        def fake_execute_stream(self_executor: SyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(SyncExecutor, "execute_stream", new=fake_execute_stream)

        class HookedAPI(APIBase):
            app_name = api_client.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_called
                post_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = HookedAPI(api_client)
        caught: Exception | None = None
        try:
            with instance.get_something.stream():
                raise ValueError("deliberate")
        except ValueError as e:
            caught = e

        assert caught is not None and str(caught) == "deliberate"
        assert post_called is False

    def test_sync_stream_merges_signature_defaults_into_payload(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that stream() merges signature defaults into the payload via get_signature_defaults"""
        captured_params: dict[str, Any] = {}

        @contextmanager
        def fake_execute_stream(self_executor: SyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            captured_params.update(params)
            yield _make_stream_response()

        mocker.patch.object(SyncExecutor, "execute_stream", new=fake_execute_stream)

        class DefaultsAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/items")
            def list_items(self, *, page: int = 1, per_page: int = Unset) -> RestResponse: ...

        instance = DefaultsAPI(api_client)
        with instance.list_items.stream():
            pass

        # page=1 default should appear; per_page=Unset should be excluded
        assert captured_params.get("json", captured_params.get("params", {})).get("page") == 1 or (
            # generate_rest_func_params puts params inside json/params key; check the raw call
            True  # verified via spy below
        )
        # Use spy to capture the merged payload sent to generate_rest_func_params
        spy_params: list[Any] = []
        original_generate = endpoint_call_util.generate_rest_func_params

        def capturing_generate(ep: Any, params: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            spy_params.append(params)
            return original_generate(ep, params, *args, **kwargs)

        mocker.patch.object(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
            side_effect=capturing_generate,
        )

        with instance.list_items.stream():
            pass

        assert spy_params, "generate_rest_func_params was not called"
        merged = spy_params[0]
        assert merged.get("page") == 1
        assert "per_page" not in merged


class TestAsyncEndpointFuncStreamCall:
    """Tests for AsyncEndpointFunc.stream()"""

    async def test_async_stream_yields_rest_response(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async stream() context manager yields a RestResponse"""
        mock_resp = _make_stream_response()

        @asynccontextmanager
        async def fake_execute_stream(self_executor: AsyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(AsyncExecutor, "execute_stream", new=fake_execute_stream)
        instance = api_class_async(api_client_async)
        async with instance.get_something.stream() as r:
            assert r is mock_resp

    async def test_async_stream_http_error_propagates(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that an HTTPError raised inside async stream() propagates to the caller"""
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("async stream connection failed")
        connect_error.request = mock_request

        class _AsyncRaisingCM:
            async def __aenter__(self) -> Any:
                raise connect_error

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch.object(AsyncExecutor, "execute_stream", return_value=_AsyncRaisingCM())
        instance = api_class_async(api_client_async)
        with pytest.raises(HTTPError, match="async stream connection failed"):
            async with instance.get_something.stream():
                pass

    async def test_async_stream_post_hook_called_after_success(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that post_request_hook is called after a successful async stream"""
        post_called = False
        mock_resp = _make_stream_response()

        @asynccontextmanager
        async def fake_execute_stream(self_executor: AsyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(AsyncExecutor, "execute_stream", new=fake_execute_stream)

        class AsyncHookedAPI(APIBase):
            app_name = api_client_async.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_called
                post_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = AsyncHookedAPI(api_client_async)
        async with instance.get_something.stream():
            pass

        assert post_called is True

    async def test_async_stream_post_hook_skipped_on_non_http_exception(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that post_request_hook is skipped on a non-HTTPError in async stream()"""
        post_called = False
        mock_resp = _make_stream_response()

        @asynccontextmanager
        async def fake_execute_stream(self_executor: AsyncExecutor, ef: Any, path: str, params: dict[str, Any]) -> Any:
            yield mock_resp

        mocker.patch.object(AsyncExecutor, "execute_stream", new=fake_execute_stream)

        class AsyncHookedAPI(APIBase):
            app_name = api_client_async.app_name

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                nonlocal post_called
                post_called = True

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = AsyncHookedAPI(api_client_async)
        caught: Exception | None = None
        try:
            async with instance.get_something.stream():
                raise RuntimeError("deliberate async")
        except RuntimeError as e:
            caught = e

        assert caught is not None and str(caught) == "deliberate async"
        assert post_called is False


class TestEndpointFuncCallWithLock:
    """Tests for EndpointFunc.with_lock()"""

    def test_auto_lock_name_uses_app_class_and_func_name(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_lock auto-generates a lock name as '{app_name}-{APIClass}.{func_name}'"""
        mocker.patch.object(Client, "request")
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock.return_value.__enter__ = mocker.MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = mocker.MagicMock(return_value=False)

        instance = api_class(api_client)
        instance.get_something.with_lock()()

        expected_lock_name = f"{api_client.app_name}-{api_class.__name__}.get_something"
        mock_lock.assert_called_once_with(expected_lock_name)

    def test_explicit_lock_name_overrides_auto_name(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that explicitly providing lock_name overrides the auto-generated name"""
        mocker.patch.object(Client, "request")
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock.return_value.__enter__ = mocker.MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = mocker.MagicMock(return_value=False)

        instance = api_class(api_client)
        instance.get_something.with_lock(lock_name="my-custom-lock")()

        mock_lock.assert_called_once_with("my-custom-lock")

    def test_lock_is_entered_and_exited_around_request(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that the Lock context manager is entered before and exited after the request"""
        call_order: list[str] = []

        mock_request = mocker.patch.object(Client, "request")

        def _request_side_effect(*a: Any, **kw: Any) -> MagicMock:
            call_order.append("request")
            return mocker.MagicMock(
                status_code=200,
                headers={},
                content=b"",
                is_stream=False,
                elapsed=mocker.MagicMock(total_seconds=lambda: 0.0),
            )

        mock_request.side_effect = _request_side_effect

        mock_lock_cls = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock_instance = mocker.MagicMock()
        mock_lock_cls.return_value = mock_lock_instance
        mock_lock_instance.__enter__ = mocker.MagicMock(side_effect=lambda: call_order.append("lock_enter"))
        mock_lock_instance.__exit__ = mocker.MagicMock(side_effect=lambda *a: call_order.append("lock_exit"))

        instance = api_class(api_client)
        instance.get_something.with_lock()()

        assert call_order == ["lock_enter", "request", "lock_exit"]

    async def test_lock_is_held_across_awaited_request_async(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that in async mode the Lock context manager is entered before and exited after the awaited request"""
        call_order: list[str] = []

        mock_request = mocker.patch.object(AsyncClient, "request")

        def _request_side_effect(*a: Any, **kw: Any) -> MagicMock:
            call_order.append("request")
            return mocker.MagicMock(
                status_code=200,
                headers={},
                content=b"",
                is_stream=False,
                elapsed=mocker.MagicMock(total_seconds=lambda: 0.0),
            )

        mock_request.side_effect = _request_side_effect

        mock_lock_cls = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.AsyncLock")
        mock_lock_instance = mocker.MagicMock()
        mock_lock_cls.return_value = mock_lock_instance
        mock_lock_instance.__aenter__.side_effect = lambda: call_order.append("lock_enter")
        mock_lock_instance.__aexit__.side_effect = lambda *a: call_order.append("lock_exit")

        instance = api_class_async(api_client_async)
        await instance.get_something.with_lock()()

        assert call_order == ["lock_enter", "request", "lock_exit"]

    def test_with_lock_returns_rest_response(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_lock returns a RestResponse"""
        mocker.patch.object(Client, "request")
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock.return_value.__enter__ = mocker.MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = mocker.MagicMock(return_value=False)

        instance = api_class(api_client)
        r = instance.get_something.with_lock()()
        assert isinstance(r, RestResponse)

    async def test_lock_is_released_after_async_call(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that the distributed lock is fully released after an awaited with_lock() call.

        Uses a real (un-mocked) Lock to catch thread-affinity bugs where acquire and release run
        on different threads, causing the OS-level file lock to silently leak.
        """
        mock_request = mocker.patch.object(AsyncClient, "request")
        mock_request.return_value = mocker.MagicMock(
            status_code=200,
            headers={},
            content=b"",
            is_stream=False,
            elapsed=mocker.MagicMock(total_seconds=lambda: 0.0),
        )
        lock_name = f"test-with-lock-{uuid4()}"

        instance = api_class_async(api_client_async)
        await instance.get_something.with_lock(lock_name=lock_name)()

        # An independent acquire of the same lock must succeed immediately after the call.
        # If the lock leaked (e.g. released on a different thread than it was acquired on),
        # this will block until the timeout and raise FileLockTimeout.
        # is_singleton=False ensures this is an independent FileLock instance that contends
        # on the OS-level flock rather than sharing the wrapper's singleton lock counter.
        try:
            with Lock(lock_name, is_singleton=False, timeout=2):
                pass
        except FileLockTimeout:
            pytest.fail("Lock was not released after the awaited with_lock() call completed")


class TestEndpointFuncCallWithRetrySync:
    """Tests for SyncEndpointFunc.with_retry()"""

    def test_no_retry_when_condition_not_met(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry does not retry when the condition is not satisfied"""
        mock_request = mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=503, num_retries=3, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert mock_request.call_count == 1

    def test_retry_on_matching_status_code(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry retries when the response matches the given status code"""
        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=503, num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_retry_on_callable_condition(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry accepts a callable condition and retries when it returns True"""
        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(429, mocker), _make_httpx_response(200, mocker)],
        )
        instance = api_class(api_client)
        r = instance.get_something.with_retry(
            condition=lambda resp: resp.status_code == 429, num_retries=1, retry_after=0
        )()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_retry_exhausts_up_to_num_retries(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry stops after num_retries retries even if condition keeps matching"""
        # 1 initial call + 2 retries = 3 total calls
        mocker.patch.object(
            Client,
            "request",
            side_effect=[
                _make_httpx_response(503, mocker),
                _make_httpx_response(503, mocker),
                _make_httpx_response(503, mocker),
            ],
        )
        instance = api_class(api_client)
        mock_request = Client.request
        r = instance.get_something.with_retry(condition=503, num_retries=2, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 503
        assert mock_request.call_count == 3

    def test_retry_passes_original_args_and_kwargs(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that with_retry forwards the original call args/kwargs to each retry"""

        class PathAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/items/{item_id}")
            def get_item(self, item_id: int) -> RestResponse: ...

        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        instance = PathAPI(api_client)
        r = instance.get_item.with_retry(condition=503, num_retries=1, retry_after=0)(item_id=42)
        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        # Both calls should have used /v1/items/42
        for call in Client.request.call_args_list:
            assert "42" in str(call)

    def test_retry_passes_correct_kwargs_to_retry_on(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry passes the correct keyword arguments to retry_on"""
        mock_retry_on = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.retry_on")
        identity: Callable[..., Any] = lambda f: f
        mock_retry_on.return_value = identity

        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        my_condition = lambda r: r.status_code == 503
        instance.get_something.with_retry(condition=my_condition, num_retries=5, retry_after=2)()

        mock_retry_on.assert_called_once_with(
            my_condition,
            num_retries=5,
            retry_after=2,
            safe_methods_only=False,
            _async_mode=False,
        )

    def test_safe_methods_only_is_forwarded_to_retry_on(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that safe_methods_only=True is forwarded to retry_on"""
        mock_retry_on = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.retry_on")
        identity: Callable[..., Any] = lambda f: f
        mock_retry_on.return_value = identity

        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        instance.get_something.with_retry(condition=503, safe_methods_only=True)()

        mock_retry_on.assert_called_once_with(
            503,
            num_retries=1,
            retry_after=5,
            safe_methods_only=True,
            _async_mode=False,
        )


class TestEndpointFuncCallWithRetryAsync:
    """Tests for AsyncEndpointFunc.with_retry()"""

    async def test_no_retry_when_condition_not_met(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_retry does not retry when the condition is not satisfied"""
        mock_request = mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_retry(condition=503, num_retries=3, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert mock_request.call_count == 1

    async def test_retry_on_matching_status_code(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_retry retries when the response matches the given status code"""
        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_retry(condition=503, num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    async def test_retry_passes_correct_kwargs_to_retry_on(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_retry passes async_mode=True to retry_on"""
        mock_retry_on = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.retry_on")
        identity: Callable[..., Any] = lambda f: f
        mock_retry_on.return_value = identity

        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        await instance.get_something.with_retry(condition=503, num_retries=1, retry_after=0)()

        mock_retry_on.assert_called_once_with(
            503,
            num_retries=1,
            retry_after=0,
            safe_methods_only=False,
            _async_mode=True,
        )

    async def test_safe_methods_only_is_forwarded_to_retry_on(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that safe_methods_only=True is forwarded to retry_on"""
        mock_retry_on = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.retry_on")
        identity: Callable[..., Any] = lambda f: f
        mock_retry_on.return_value = identity

        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        await instance.get_something.with_retry(condition=503, safe_methods_only=True)()

        mock_retry_on.assert_called_once_with(
            503,
            num_retries=1,
            retry_after=5,
            safe_methods_only=True,
            _async_mode=True,
        )


class TestEndpointFuncCallWithRetryOnException:
    """Tests for with_retry() using exception classes as the condition"""

    def test_sync_retry_on_matching_exception_class(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry retries when the raised exception matches the condition class"""
        call_count = 0

        def request_side_effect(*a: Any, **kw: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("transient error")
            return _make_httpx_response(200, mocker)

        mocker.patch.object(Client, "request", side_effect=request_side_effect)
        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=ValueError, num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert call_count == 2

    def test_sync_no_retry_on_non_matching_exception_class(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry does not retry when the raised exception does not match the condition class"""
        mocker.patch.object(Client, "request", side_effect=TypeError("unexpected type"))
        instance = api_class(api_client)
        with pytest.raises(TypeError):
            instance.get_something.with_retry(condition=ValueError, num_retries=1, retry_after=0)()

    def test_sync_retry_on_tuple_of_exception_classes(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry retries when the raised exception matches any class in a tuple condition"""
        call_count = 0

        def request_side_effect(*a: Any, **kw: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TypeError("type error")
            return _make_httpx_response(200, mocker)

        mocker.patch.object(Client, "request", side_effect=request_side_effect)
        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=(ValueError, TypeError), num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert call_count == 2

    def test_sync_retry_exhausts_up_to_num_retries_on_exception(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry stops after num_retries retries even if the exception keeps being raised"""
        mocker.patch.object(Client, "request", side_effect=ValueError("always fails"))
        instance = api_class(api_client)
        with pytest.raises(ValueError):
            instance.get_something.with_retry(condition=ValueError, num_retries=2, retry_after=0)()
        # 1 initial call + 2 retries = 3 total
        assert Client.request.call_count == 3

    def test_sync_safe_methods_only_skips_retry_for_unsafe_method(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that safe_methods_only=True skips retry when the endpoint uses a non-safe HTTP method"""

        class PostAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/something")
            def post_something(self) -> RestResponse: ...

        mocker.patch.object(
            Client, "request", side_effect=lambda *a, **kw: _raise_with_request(ValueError("transient error"), "POST")
        )
        instance = PostAPI(api_client)
        with pytest.raises(ValueError):
            instance.post_something.with_retry(
                condition=ValueError, num_retries=2, retry_after=0, safe_methods_only=True
            )()
        assert Client.request.call_count == 1

    def test_sync_safe_methods_only_retries_for_safe_method(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that safe_methods_only=True still retries when the endpoint uses a safe HTTP method (GET)"""
        call_count = 0

        def request_side_effect(*a: Any, **kw: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                _raise_with_request(ValueError("transient error"), "GET")
            return _make_httpx_response(200, mocker)

        mocker.patch.object(Client, "request", side_effect=request_side_effect)
        instance = api_class(api_client)
        r = instance.get_something.with_retry(
            condition=ValueError, num_retries=1, retry_after=0, safe_methods_only=True
        )()
        assert isinstance(r, RestResponse)
        assert call_count == 2

    async def test_async_retry_on_matching_exception_class(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_retry retries when the raised exception matches the condition class"""
        call_count = 0

        def request_side_effect(*a: Any, **kw: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("transient error")
            return _make_httpx_response(200, mocker)

        mocker.patch.object(AsyncClient, "request", side_effect=request_side_effect)
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_retry(condition=ValueError, num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert call_count == 2

    async def test_async_safe_methods_only_skips_retry_for_unsafe_method(
        self, mocker: MockerFixture, api_client_async: APIClient
    ) -> None:
        """Test that in async mode safe_methods_only=True skips retry for non-safe HTTP methods"""

        class PostAPI(APIBase):
            app_name = api_client_async.app_name

            @endpoint.post("/v1/something")
            def post_something(self) -> RestResponse: ...

        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=lambda *a, **kw: _raise_with_request(ValueError("transient error"), "POST"),
        )
        instance = PostAPI(api_client_async)
        with pytest.raises(ValueError):
            await instance.post_something.with_retry(
                condition=ValueError, num_retries=2, retry_after=0, safe_methods_only=True
            )()
        assert AsyncClient.request.call_count == 1

    async def test_async_safe_methods_only_retries_for_safe_method(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that in async mode safe_methods_only=True still retries for safe HTTP methods (GET)"""
        call_count = 0

        def request_side_effect(*a: Any, **kw: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                _raise_with_request(ValueError("transient error"), "GET")
            return _make_httpx_response(200, mocker)

        mocker.patch.object(AsyncClient, "request", side_effect=request_side_effect)
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_retry(
            condition=ValueError, num_retries=1, retry_after=0, safe_methods_only=True
        )()
        assert isinstance(r, RestResponse)
        assert call_count == 2


class TestEndpointFuncCallWithExpectedStatus:
    """Tests for EndpointFunc.with_expected_status()"""

    def test_sync_passes_through_when_status_matches(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status returns the RestResponse when the status code matches"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        r = instance.get_something.with_expected_status(200)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_sync_raises_assertion_when_status_does_not_match(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status raises AssertionError when the status code does not match"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(404, mocker))
        instance = api_class(api_client)
        with pytest.raises(AssertionError, match=r"Expected status code 200, but got 404"):
            instance.get_something.with_expected_status(200)()

    def test_sync_accepts_multiple_expected_statuses(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status accepts multiple codes and passes when any one matches"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(201, mocker))
        instance = api_class(api_client)
        r = instance.get_something.with_expected_status(200, 201)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 201

    def test_sync_raises_when_none_of_multiple_statuses_match(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status raises AssertionError when none of the expected codes match"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(400, mocker))
        instance = api_class(api_client)
        with pytest.raises(AssertionError, match=r"Expected status code 200/201, but got 400"):
            instance.get_something.with_expected_status(200, 201)()

    def test_sync_useful_for_negative_test_scenarios(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status can assert on error status codes for negative test scenarios"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(400, mocker))
        instance = api_class(api_client)
        r = instance.get_something.with_expected_status(400, 422)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 400

    def test_raises_value_error_when_called_with_no_statuses(
        self, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status raises ValueError immediately when given no status codes"""
        instance = api_class(api_client)
        with pytest.raises(ValueError, match="At least one expected status code must be given"):
            instance.get_something.with_expected_status()

    async def test_async_passes_through_when_status_matches(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_expected_status returns the RestResponse when the status code matches"""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_expected_status(200)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    async def test_async_raises_assertion_when_status_does_not_match(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_expected_status raises AssertionError when the status code does not match"""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(404, mocker))
        instance = api_class_async(api_client_async)
        with pytest.raises(AssertionError, match=r"Expected status code 200, but got 404"):
            await instance.get_something.with_expected_status(200)()


class TestEndpointFuncCallWithMaxResponseTime:
    """Tests for EndpointFunc.with_max_response_time()"""

    def test_sync_passes_when_response_time_is_within_limit(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_max_response_time returns the response when the response time is within the limit"""
        resp = _make_httpx_response(200, mocker)
        resp.elapsed.total_seconds.return_value = 100 / 1000
        mocker.patch.object(Client, "request", return_value=resp)
        instance = api_class(api_client)
        r = instance.get_something.with_max_response_time(1000)()
        assert isinstance(r, RestResponse)

    def test_sync_raises_assertion_when_response_time_exceeds_limit(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_max_response_time raises AssertionError when the response time exceeds the limit"""
        resp = _make_httpx_response(200, mocker)
        resp.elapsed.total_seconds.return_value = 200 / 1000
        mocker.patch.object(Client, "request", return_value=resp)
        instance = api_class(api_client)
        with pytest.raises(AssertionError, match=r"Response time 200 msecs exceeded the threshold of 100 msecs"):
            instance.get_something.with_max_response_time(100)()

    def test_sync_passes_when_response_time_equals_limit(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_max_response_time passes when response time exactly equals the limit (boundary: > not >=)"""
        resp = _make_httpx_response(200, mocker)
        resp.elapsed.total_seconds.return_value = 100 / 1000
        mocker.patch.object(Client, "request", return_value=resp)
        instance = api_class(api_client)
        r = instance.get_something.with_max_response_time(100)()
        assert isinstance(r, RestResponse)

    async def test_async_passes_when_response_time_is_within_limit(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_max_response_time returns the response when the response time is within the limit"""
        resp = _make_httpx_response(200, mocker)
        resp.elapsed.total_seconds.return_value = 100 / 1000
        mocker.patch.object(AsyncClient, "request", return_value=resp)
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_max_response_time(1000)()
        assert isinstance(r, RestResponse)

    async def test_async_raises_assertion_when_response_time_exceeds_limit(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_max_response_time raises AssertionError when the response time exceeds the limit"""
        resp = _make_httpx_response(200, mocker)
        resp.elapsed.total_seconds.return_value = 200 / 1000
        mocker.patch.object(AsyncClient, "request", return_value=resp)
        instance = api_class_async(api_client_async)
        with pytest.raises(AssertionError, match=r"Response time 200 msecs exceeded the threshold of 100 msecs"):
            await instance.get_something.with_max_response_time(100)()


class TestEndpointFuncCallWithPolling:
    """Tests for EndpointFunc.with_polling()"""

    def test_sync_returns_immediately_when_condition_met_on_first_call(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_polling returns on the first call when until() is immediately True"""
        mock_request = mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        mocker.patch("time.sleep")
        instance = api_class(api_client)
        r = instance.get_something.with_polling(until=lambda resp: resp.ok, interval=0.1, timeout=60)()
        assert isinstance(r, RestResponse)
        assert mock_request.call_count == 1

    def test_sync_polls_until_condition_is_met(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_polling keeps calling the endpoint until until() returns True"""
        # First two calls return 202 (condition False); third returns 200 (condition True)
        mocker.patch.object(
            Client,
            "request",
            side_effect=[
                _make_httpx_response(202, mocker),
                _make_httpx_response(202, mocker),
                _make_httpx_response(200, mocker),
            ],
        )
        # Patch time in endpoint_func's namespace only so asyncio's internal time.monotonic() is unaffected.
        # Return values: deadline_call=0.0, check_after_1st_poll=1.0, check_after_2nd_poll=2.0
        mock_time = mocker.MagicMock()
        mock_time.monotonic.side_effect = [0.0, 1.0, 2.0]
        mocker.patch.object(_endpoint_func_module, "time", mock_time)
        instance = api_class(api_client)
        r = instance.get_something.with_polling(until=lambda resp: resp.status_code == 200, interval=0.5, timeout=60)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        assert Client.request.call_count == 3
        assert mock_time.sleep.call_count == 2
        mock_time.sleep.assert_called_with(0.5)

    def test_sync_raises_timeout_when_condition_never_met(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_polling raises TimeoutError when the condition is never satisfied within timeout"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(202, mocker))
        # deadline = 0.0 + 5 = 5.0; after one failed poll, monotonic returns 10.0 → 10.0 + 0.1 >= 5.0
        mock_time = mocker.MagicMock()
        mock_time.monotonic.side_effect = [0.0, 10.0]
        mocker.patch.object(_endpoint_func_module, "time", mock_time)
        instance = api_class(api_client)
        with pytest.raises(TimeoutError, match="Polling condition was not met within 5 seconds"):
            instance.get_something.with_polling(until=lambda resp: resp.status_code == 200, interval=0.1, timeout=5)()

    def test_sync_endpoint_is_always_called_at_least_once(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_polling always makes at least one request even with a very short timeout"""
        mock_request = mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        # condition immediately True → returns after first call without even checking the deadline
        instance = api_class(api_client)
        instance.get_something.with_polling(until=lambda resp: resp.ok, timeout=0)()
        assert mock_request.call_count == 1

    async def test_async_returns_immediately_when_condition_met_on_first_call(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_polling returns on the first call when until() is immediately True"""
        mock_request = mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_polling(until=lambda resp: resp.ok, interval=0, timeout=60)()
        assert isinstance(r, RestResponse)
        assert mock_request.call_count == 1

    async def test_async_polls_until_condition_is_met(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_polling keeps calling the endpoint until until() returns True"""
        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=[
                _make_httpx_response(202, mocker),
                _make_httpx_response(202, mocker),
                _make_httpx_response(200, mocker),
            ],
        )
        mock_sleep = mocker.patch("asyncio.sleep")
        # Patch time in endpoint_func's namespace only so asyncio's internal time.monotonic() is unaffected.
        # Return values: deadline_call=0.0, check_after_1st_poll=1.0, check_after_2nd_poll=2.0
        mock_time = mocker.MagicMock()
        mock_time.monotonic.side_effect = [0.0, 1.0, 2.0]
        mocker.patch.object(_endpoint_func_module, "time", mock_time)
        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_polling(
            until=lambda resp: resp.status_code == 200, interval=0.5, timeout=60
        )()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        assert AsyncClient.request.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(0.5)

    async def test_async_raises_timeout_when_condition_never_met(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_polling raises TimeoutError when the condition is never satisfied within timeout"""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(202, mocker))
        mocker.patch("asyncio.sleep")
        # deadline = 0.0 + 5 = 5.0; after one failed poll, monotonic returns 10.0 → 10.0 + 0.1 >= 5.0
        mock_time = mocker.MagicMock()
        mock_time.monotonic.side_effect = [0.0, 10.0]
        mocker.patch.object(_endpoint_func_module, "time", mock_time)
        instance = api_class_async(api_client_async)
        with pytest.raises(TimeoutError, match="Polling condition was not met within 5 seconds"):
            await instance.get_something.with_polling(
                until=lambda resp: resp.status_code == 200, interval=0.1, timeout=5
            )()


class TestEndpointFuncCallWithChaining:
    """Tests for chaining multiple with_xxx() wrappers"""

    def test_sync_with_lock_then_with_retry(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_lock().with_retry() acquires the lock AND retries on the given condition.

        Because with_lock() is the outer wrapper (first in chain), it wraps the entire retry sequence:
        the lock is acquired once and held for all retry attempts.
        """
        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock.return_value.__enter__ = mocker.MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = mocker.MagicMock(return_value=False)

        instance = api_class(api_client)
        r = instance.get_something.with_lock().with_retry(condition=503, num_retries=1, retry_after=0)()

        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        # Lock wraps the whole retry sequence: acquired once, held for all attempts
        assert mock_lock.call_count == 1

    def test_sync_with_retry_then_with_lock(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry().with_lock() acquires the lock AND retries on the given condition.

        Because with_retry() is the outer wrapper (first in chain), it wraps the lock:
        the lock is acquired on each individual attempt (= num_retries + 1 total).
        """
        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.Lock")
        mock_lock.return_value.__enter__ = mocker.MagicMock(return_value=None)
        mock_lock.return_value.__exit__ = mocker.MagicMock(return_value=False)

        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=503, num_retries=1, retry_after=0).with_lock()()

        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        # Lock is acquired once per attempt: initial try + 1 retry = 2 total
        assert mock_lock.call_count == 2

    async def test_async_with_lock_then_with_retry(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_lock().with_retry() acquires the lock AND retries on the given condition.

        Because with_lock() is the outer wrapper (first in chain), it wraps the entire retry sequence:
        the lock is acquired once and held for all retry attempts.
        """
        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        mock_lock = mocker.patch("openapi_test_client.libraries.core.endpoints.endpoint_func.AsyncLock")

        instance = api_class_async(api_client_async)
        r = await instance.get_something.with_lock().with_retry(condition=503, num_retries=1, retry_after=0)()

        assert isinstance(r, RestResponse)
        assert r.status_code == 200
        # Lock wraps the whole retry sequence: acquired once, held for all attempts
        assert mock_lock.call_count == 1

    def test_sync_with_expected_status_then_with_retry(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_expected_status().with_retry() asserts on the final response after retries.

        Because with_expected_status() is the outer wrapper (first in chain), it asserts after
        the entire retry sequence has finished — not on each individual attempt.
        """
        # First call returns 503 (retry condition); second returns 200 (retry ends, assertion passes)
        mocker.patch.object(
            Client,
            "request",
            side_effect=[_make_httpx_response(503, mocker), _make_httpx_response(200, mocker)],
        )
        instance = api_class(api_client)
        r = instance.get_something.with_expected_status(200).with_retry(condition=503, num_retries=1, retry_after=0)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_sync_with_polling_then_with_expected_status(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_polling().with_expected_status() applies status assertion on each polled response.

        Because with_polling() is the outer wrapper (first in chain), it re-invokes with_expected_status()
        on every poll — meaning an unexpected status on an intermediate poll raises immediately.
        """
        # All responses are 200 (both assertion and polling condition pass on first call)
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        mocker.patch("time.sleep")
        instance = api_class(api_client)
        r = instance.get_something.with_polling(until=lambda resp: resp.ok, timeout=60).with_expected_status(200)()
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_sync_terminal_wrapper_in_the_middle_raises(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that chaining any wrapper after a terminal one raises TypeError at chain-build time."""
        instance = api_class(api_client)
        with pytest.raises(RuntimeError, match="terminal"):
            instance.get_something.with_concurrency().with_retry()

    def test_sync_terminal_wrapper_after_another_terminal_raises(
        self, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that chaining a second terminal wrapper after the first raises TypeError."""
        instance = api_class(api_client)
        with pytest.raises(RuntimeError, match="terminal"):
            instance.get_something.with_concurrency().with_repeat()

    def test_sync_repeat_terminal_wrapper_in_the_middle_raises(
        self, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that chaining any wrapper after with_repeat() raises TypeError."""
        instance = api_class(api_client)
        with pytest.raises(RuntimeError, match="terminal"):
            instance.get_something.with_repeat().with_expected_status(200)

    async def test_async_terminal_wrapper_in_the_middle_raises(
        self, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that chaining any wrapper after a terminal one raises TypeError in async mode."""
        instance = api_class_async(api_client_async)
        with pytest.raises(RuntimeError, match="terminal"):
            instance.get_something.with_concurrency().with_retry()


class TestEndpointFuncCallWithRepeat:
    """Tests for with_repeat() — sequential repeated calls that collect all results"""

    def test_sync_with_repeat_returns_all_responses_on_success(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat in sync mode fires N sequential calls and returns all responses"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, SyncEndpointFunc)

        results = endpoint_func.with_repeat(num=3)()
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert Client.request.call_count == 3

    def test_sync_with_repeat_collects_exceptions_without_propagating(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat collects raised exceptions in-order without stopping the loop"""
        mocker.patch.object(
            Client,
            "request",
            side_effect=[
                _make_httpx_response(200, mocker),
                ValueError("transient error"),
                _make_httpx_response(201, mocker),
            ],
        )
        instance = api_class(api_client)

        # Must not raise despite the middle call failing
        results = instance.get_something.with_repeat(num=3, return_exceptions=True)()

        assert len(results) == 3
        assert isinstance(results[0], RestResponse)
        assert isinstance(results[1], ValueError)
        assert isinstance(results[2], RestResponse)
        # All N calls ran
        assert Client.request.call_count == 3

    def test_sync_with_repeat_collects_all_exceptions(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat collects all failures when every call raises"""
        num = 3
        mocker.patch.object(Client, "request", side_effect=ValueError("always fails"))
        instance = api_class(api_client)

        results = instance.get_something.with_repeat(num=num, return_exceptions=True)()

        assert len(results) == num
        assert all(isinstance(r, ValueError) for r in results)
        assert Client.request.call_count == num

    def test_sync_with_repeat_propagates_exception_by_default(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat propagates exceptions and stops on first failure by default"""
        mocker.patch.object(
            Client,
            "request",
            side_effect=[
                _make_httpx_response(200, mocker),
                ValueError("transient error"),
                _make_httpx_response(200, mocker),
            ],
        )
        instance = api_class(api_client)

        with pytest.raises(ValueError):
            instance.get_something.with_repeat(num=3)()

        # Stopped after the first exception — third call never made
        assert Client.request.call_count == 2

    def test_sync_with_repeat_default_num(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat() uses the default of 2 calls when num is not specified"""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)

        results = instance.get_something.with_repeat()()

        assert len(results) == 2
        assert Client.request.call_count == 2

    async def test_async_with_repeat_returns_all_responses_on_success(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that with_repeat in async mode fires N sequential calls and returns all responses"""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, AsyncEndpointFunc)

        results = await endpoint_func.with_repeat(num=3)()
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert AsyncClient.request.call_count == 3

    async def test_async_with_repeat_collects_exceptions_without_propagating(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_repeat collects raised exceptions in-order without stopping the loop"""
        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=[
                _make_httpx_response(200, mocker),
                ValueError("transient error"),
                _make_httpx_response(201, mocker),
            ],
        )
        instance = api_class_async(api_client_async)

        # Must not raise despite the middle call failing
        results = await instance.get_something.with_repeat(num=3, return_exceptions=True)()

        assert len(results) == 3
        assert isinstance(results[0], RestResponse)
        assert isinstance(results[1], ValueError)
        assert isinstance(results[2], RestResponse)
        # All N calls ran
        assert AsyncClient.request.call_count == 3

    async def test_async_with_repeat_collects_all_exceptions(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_repeat collects all failures when every call raises"""
        num = 3
        mocker.patch.object(AsyncClient, "request", side_effect=ValueError("always fails"))
        instance = api_class_async(api_client_async)

        results = await instance.get_something.with_repeat(num=num, return_exceptions=True)()

        assert len(results) == num
        assert all(isinstance(r, ValueError) for r in results)
        assert AsyncClient.request.call_count == num

    async def test_async_with_repeat_propagates_exception_by_default(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_repeat propagates exceptions and stops on first failure by default"""
        mocker.patch.object(
            AsyncClient,
            "request",
            side_effect=[
                _make_httpx_response(200, mocker),
                ValueError("transient error"),
                _make_httpx_response(200, mocker),
            ],
        )
        instance = api_class_async(api_client_async)

        with pytest.raises(ValueError):
            await instance.get_something.with_repeat(num=3)()

        # Stopped after the first exception — third call never made
        assert AsyncClient.request.call_count == 2

    async def test_async_with_repeat_default_num(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that async with_repeat() uses the default of 2 calls when num is not specified"""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)

        results = await instance.get_something.with_repeat()()

        assert len(results) == 2
        assert AsyncClient.request.call_count == 2


class TestEndpointFuncCallWithStats:
    """Tests for EndpointFunc.with_stats()."""

    @pytest.fixture(autouse=True)
    def reset_stats(self) -> Generator[None, None, None]:
        """Reset the global Stats collector and restore enabled state before and after each test."""
        Stats.reset()
        Stats.enable()
        yield
        Stats.reset()
        Stats.enable()

    def test_sync_with_stats_returns_response_and_shows_report(
        self,
        mocker: MockerFixture,
        api_client: APIClient,
        api_class: type[APIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that with_stats() returns a RestResponse and prints a stats report without the Endpoint column."""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)

        assert isinstance(instance.get_something, SyncEndpointFunc)

        r = instance.get_something.with_stats()()

        assert isinstance(r, RestResponse)
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "GET /v1/something" not in output

    def test_sync_with_stats_shows_report_on_failure(
        self,
        mocker: MockerFixture,
        api_client: APIClient,
        api_class: type[APIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that with_stats() prints the stats report even when the call raises an exception."""
        mocker.patch.object(Client, "request", side_effect=ValueError("simulated failure"))
        instance = api_class(api_client)

        with pytest.raises(ValueError):
            instance.get_something.with_stats()()

        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "GET /v1/something" not in output

    def test_sync_with_stats_show_failure_does_not_mask_call_outcome(
        self,
        mocker: MockerFixture,
        api_client: APIClient,
        api_class: type[APIBase],
    ) -> None:
        """Test that a failure in the report printing neither masks the call's exception nor breaks its result."""
        mocker.patch.object(StatsCollector, "show", side_effect=RuntimeError("simulated show failure"))
        instance = api_class(api_client)

        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        r = instance.get_something.with_stats()()
        assert isinstance(r, RestResponse)

        mocker.patch.object(Client, "request", side_effect=ValueError("simulated failure"))
        with pytest.raises(ValueError, match="simulated failure"):
            instance.get_something.with_stats()()

    def test_sync_with_stats_composes_with_concurrency(
        self,
        mocker: MockerFixture,
        api_client: APIClient,
        api_class: type[APIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that with_stats().with_concurrency() aggregates all concurrent calls in the report."""
        mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)

        results = instance.get_something.with_stats().with_concurrency(num=3)()

        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert Client.request.call_count == 3
        stat = Stats.get("GET /v1/something")
        assert stat is not None
        assert stat.num_calls == 3
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "GET /v1/something" not in output

    async def test_async_with_stats_returns_response_and_shows_report(
        self,
        mocker: MockerFixture,
        api_client_async: APIClient,
        api_class_async: type[APIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that async with_stats() returns a RestResponse and prints a stats report without the Endpoint column."""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)

        assert isinstance(instance.get_something, AsyncEndpointFunc)

        r = await instance.get_something.with_stats()()

        assert isinstance(r, RestResponse)
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "GET /v1/something" not in output

    async def test_async_with_stats_composes_with_concurrency(
        self,
        mocker: MockerFixture,
        api_client_async: APIClient,
        api_class_async: type[APIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that async with_stats().with_concurrency() aggregates all concurrent calls in the report."""
        mocker.patch.object(AsyncClient, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class_async(api_client_async)

        results = await instance.get_something.with_stats().with_concurrency(num=3)()

        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert AsyncClient.request.call_count == 3
        stat = Stats.get("GET /v1/something")
        assert stat is not None
        assert stat.num_calls == 3
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "GET /v1/something" not in output


def _make_stream_response() -> MagicMock:
    """Return a MagicMock that looks like a streaming RestResponse."""
    r = MagicMock(spec=RestResponse)
    r.is_stream = True
    r.status_code = 200
    return r


def _make_httpx_response(status_code: int, mocker: MockerFixture) -> ResponseExt:
    """Build a minimal mock httpx response with the given status code."""
    r = mocker.MagicMock(spec=ResponseExt)
    r.status_code = status_code
    r.headers = {}
    r.content = b""
    r.is_stream = False
    r.elapsed = mocker.MagicMock()
    r.elapsed.total_seconds.return_value = 0.0
    r.json.return_value = {}
    r.text = ""
    return r


def _raise_with_request(exc: Exception, method: str) -> NoReturn:
    """Attach a request with the given HTTP method to the exception and raise it.

    Mimics common-libs' RestClient.send(), which attaches the original request to any raised
    exception so retry_on() can read the HTTP method for its safe_methods_only check.

    :param exc: Exception to raise
    :param method: HTTP method string (e.g. "GET", "POST") to embed in the attached request
    """
    set_request_to_exception(exc, RequestExt(method, "https://example.com/api/v1/something"))
    raise exc
