"""Unit tests for endpoints_func.py"""

import re
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import MISSING
from functools import wraps
from typing import Annotated, Any
from unittest.mock import MagicMock

import pytest
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import ResponseExt
from httpx import AsyncClient, Client, ConnectError, HTTPError, Request
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.utils.endpoint_call as endpoint_call_util
from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.core.endpoints import (
    AsyncEndpointFunc,
    Endpoint,
    EndpointFunc,
    SyncEndpointFunc,
    endpoint,
)
from openapi_test_client.libraries.core.endpoints.executors import AsyncExecutor, SyncExecutor
from openapi_test_client.libraries.core.types import Alias, EndpointModel, Query, Unset

pytestmark = [pytest.mark.unittest]


class TestEndpointFunc:
    """Tests for core EndpointFunc behavior"""

    @pytest.mark.parametrize("api_client", ["sync", "async"], indirect=True)
    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_func_access(self, api_client: APIClient, api_class: type[APIBase], access_by: str) -> None:
        """Test that accessing endpoint via API class or instance returns an EndpointFunc, and the correct subclass
        based on async_mode
        """
        if access_by == "instance":
            api_class_or_instance = api_class(api_client)
        else:
            api_class_or_instance = api_class
        endpoint_func = api_class_or_instance.get_something
        assert isinstance(endpoint_func, EndpointFunc)

        if access_by == "instance" and api_client.async_mode:
            assert isinstance(endpoint_func, AsyncEndpointFunc)
        else:
            assert isinstance(endpoint_func, SyncEndpointFunc)

    def test_repr(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.__repr__ contains 'mapped to' reference to original function"""
        instance = api_class(api_client)
        repr_str = repr(instance.get_something)
        assert "mapped to" in repr_str

    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_property_returns_endpoint_object(
        self, api_client: APIClient, api_class: type[APIBase], access_by: str
    ) -> None:
        """Test that EndpointFunc.endpoint returns an Endpoint object"""
        if access_by == "instance":
            api_class_or_instance = api_class(api_client)
        else:
            api_class_or_instance = api_class
        endpoint = api_class_or_instance.get_something.endpoint
        assert isinstance(endpoint, Endpoint)

    def test_model_property_returns_endpoint_model(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.model returns a subclass of EndpointModel"""

        instance = api_class(api_client)
        endpoint_func = instance.get_something
        endpoint_model = endpoint_func.model
        assert issubclass(endpoint_model, EndpointModel)

    def test_model_property_name(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.model name follows <APIClass><FuncName>EndpointModel convention"""

        instance = api_class(api_client)
        endpoint_func = instance.get_something
        assert endpoint_func.model.__name__ == "TestAPIGetSomethingEndpointModel"

    def test_endpoint_func_call_requires_instance(self, api_class: type[APIBase]) -> None:
        """Test that calling __call__() raises TypeError when accessed without an API instance"""
        endpoint_func = api_class.get_something
        assert endpoint_func._instance is None
        with pytest.raises(
            TypeError,
            match=re.escape(
                f"You can not access {endpoint_func.__name__}() directly through the {api_class.__name__} class."
            ),
        ):
            endpoint_func()

    def test_requires_instance_method_name_for_non_call_method(self, api_class: type[APIBase]) -> None:
        """Test that requires_instance uses the method name (not original func name) for non-__call__ methods

        requires_instance has branching logic: it uses self._original_func.__name__ when f.__name__ == "__call__"
        but f.__name__ otherwise. This test covers the non-__call__ branch (e.g. with_retry).
        """
        endpoint_func = api_class.get_something
        assert endpoint_func._instance is None
        with pytest.raises(
            TypeError,
            match=re.escape(f"You can not access with_retry() directly through the {api_class.__name__} class."),
        ):
            endpoint_func.with_retry()


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

        results = endpoint_func.with_concurrency(num=3)
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert mock_httpx_request.call_count == 3

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

        results = await endpoint_func.with_concurrency(num=3)
        assert len(results) == 3
        assert all(isinstance(r, RestResponse) for r in results)
        assert mock_httpx_request.call_count == 3

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
        instance.get_something.with_lock()

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
        instance.get_something.with_lock(lock_name="my-custom-lock")

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
        instance.get_something.with_lock()

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
        r = instance.get_something.with_lock()
        assert isinstance(r, RestResponse)


class TestEndpointFuncCallWithRetrySync:
    """Tests for SyncEndpointFunc.with_retry()"""

    def test_no_retry_when_condition_not_met(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry does not retry when the condition is not satisfied"""
        mock_request = mocker.patch.object(Client, "request", return_value=_make_httpx_response(200, mocker))
        instance = api_class(api_client)
        r = instance.get_something.with_retry(condition=503, num_retry=3, retry_after=0)
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
        r = instance.get_something.with_retry(condition=503, num_retry=1, retry_after=0)
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
            condition=lambda resp: resp.status_code == 429, num_retry=1, retry_after=0
        )
        assert isinstance(r, RestResponse)
        assert r.status_code == 200

    def test_retry_exhausts_up_to_num_retry(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_retry stops after num_retry retries even if condition keeps matching"""
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
        r = instance.get_something.with_retry(condition=503, num_retry=2, retry_after=0)
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
        r = instance.get_item.with_retry(42, condition=503, num_retry=1, retry_after=0)
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
        instance.get_something.with_retry(condition=my_condition, num_retry=5, retry_after=2)

        mock_retry_on.assert_called_once_with(
            my_condition,
            num_retry=5,
            retry_after=2,
            safe_methods_only=False,
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
        r = await instance.get_something.with_retry(condition=503, num_retry=3, retry_after=0)
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
        r = await instance.get_something.with_retry(condition=503, num_retry=1, retry_after=0)
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
        await instance.get_something.with_retry(condition=503, num_retry=1, retry_after=0)

        mock_retry_on.assert_called_once_with(
            503,
            num_retry=1,
            retry_after=0,
            safe_methods_only=False,
            _async_mode=True,
        )


class TestSyncEndpointFuncStream:
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


class TestAsyncEndpointFuncStream:
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


class TestEndpointFuncSignatureDefaults:
    """Tests for signature-default merging and Unset-exclusion behavior."""

    @pytest.fixture(autouse=True)
    def _mock_request(self, mocker: MockerFixture) -> None:
        mocker.patch.object(Client, "request")

    @pytest.fixture(autouse=True)
    def spy_generate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

    def test_defaults_merged_to_payload(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that endpoint signature defaults are included in the request payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = "anon", count: int = 0, tag: str | None = None) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item()

        spy_generate.assert_called_once()
        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {"name": "anon", "count": 0, "tag": None}

    def test_unset_is_excluded_from_payload(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that endpoint signature defaults with the Unset sentinel are excluded from the request payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = Unset, count: int = Unset, tag: str = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item()

        spy_generate.assert_called_once()
        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {}

    def test_explicit_params_override_defaults(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that explicitly-supplied params override signature defaults in the payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = "anon", count: int = 0, tag: str = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item(name="alice", count=5, tag="thing")

        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {"name": "alice", "count": 5, "tag": "thing"}


class TestEndpointFuncFlexibleParamDefinition:
    """Tests for the flexible parameter definition feature.

    Path parameters are identified by matching their names against {placeholder} tokens in the endpoint path.
    Both path and Non-path parameters can be passed either positionally or as keyword arguments.
    """

    def _make_api(self, api_client: APIClient) -> type[APIBase]:
        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer(self, customer_id: int, customer_type: str) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}/orders/{order_id}")
            def get_order(self, customer_id: int, order_id: int, status: str) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer_with_defaults(
                self, customer_id: int = 99, customer_type: str | None = None
            ) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer_positional_only(self, customer_id: int, /, customer_type: str) -> RestResponse: ...

        return TestAPI

    def _spy_path_and_params(self, mocker: MockerFixture) -> Any:
        mocker.patch.object(Client, "request")
        return mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["validate_path_and_params"]),
            "validate_path_and_params",
        )

    @staticmethod
    def _body_params(spy: Any) -> dict[str, Any]:
        """Extract body/query params from validate_path_and_params spy call args."""
        return {k: v for k, v in spy.call_args.kwargs.items() if k != "raw_options"}

    def test_path_positional_body_positional(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that both path and body params can be passed positionally."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(1, "premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_path_positional_body_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that path param is positional while body param is a keyword argument."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(1, customer_type="premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_path_keyword_body_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that path and body params are both passed as keyword arguments."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(customer_id=1, customer_type="premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_multiple_path_params_positional(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that multiple path params can be passed positionally with body mixed in."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_order(10, 42, "active")

        assert spy.spy_return == "/v1/customers/10/orders/42"
        assert self._body_params(spy) == {"status": "active"}

    def test_multiple_path_params_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that multiple path params can be passed as keyword arguments."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_order(order_id=42, customer_id=10, status="active")

        assert spy.spy_return == "/v1/customers/10/orders/42"
        assert self._body_params(spy) == {"status": "active"}

    def test_path_param_default_applied_when_omitted(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a path parameter's signature default is used when the caller omits it."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_with_defaults()  # customer_id defaults to 99

        assert spy.spy_return == "/v1/customers/99"
        assert self._body_params(spy) == {}

    def test_path_param_default_overridden(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an explicitly supplied value overrides the path param's default."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_with_defaults(customer_id=5)

        assert spy.spy_return == "/v1/customers/5"
        assert self._body_params(spy) == {}

    def test_body_param_default_not_auto_applied_to_hook(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that body/query param defaults are NOT auto-included in pre_request_hook kwargs."""
        captured: list[dict[str, Any]] = []

        class TestAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, endpoint: Any, *args: Any, **params: Any) -> None:
                captured.append(dict(params))

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer(self, customer_id: int = 99, customer_type: str | None = None) -> RestResponse: ...

        mocker.patch.object(Client, "request")
        instance = TestAPI(api_client)
        instance.get_customer()  # neither supplied

        # Hook should see only user-provided body/query params (none in this call)
        assert captured == [{}]

    def test_positional_only_path_param(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that existing positional-only path param works."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_positional_only(7, "vip")

        assert spy.spy_return == "/v1/customers/7"
        assert self._body_params(spy) == {"customer_type": "vip"}

    def test_missing_required_path_param_raises(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that omitting a required path param (no default) raises a descriptive ValueError."""
        mocker.patch.object(Client, "request")
        instance = self._make_api(api_client)(api_client)

        with pytest.raises(ValueError, match="missing 1 required path parameter"):
            instance.get_customer(customer_type="premium")  # customer_id omitted

    def test_non_identifier_placeholder_matched_by_cleaned_name_positional(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that {customer-id} placeholder is matched against the cleaned param name 'customer_id'."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer(42)

        assert spy.spy_return == "/v1/customers/42"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_matched_by_cleaned_name_keyword(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that {customer-id} placeholder is matched when the param is passed as a keyword argument."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer(customer_id=42)

        assert spy.spy_return == "/v1/customers/42"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_default_applied(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a signature default is applied for a non-identifier placeholder param."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int = 7) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer()  # uses default

        assert spy.spy_return == "/v1/customers/7"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_model_categorization(self, api_client: APIClient) -> None:
        """Test that create_endpoint_model recognises a cleaned-name param as a path field."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int, role: str) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_customer.model
        fields = model.__dataclass_fields__

        # customer_id matched {customer-id} → path field, no default
        assert "customer_id" in fields
        assert fields["customer_id"].default is MISSING
        # role is body/query → has default (Unset)
        assert fields["role"].default is not MISSING

    def test_non_identifier_placeholder_body_default_not_leaked(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that a body/query default is not leaked into the hook when using a non-identifier placeholder."""
        captured: list[dict[str, Any]] = []

        class TestAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, endpoint: Any, *args: Any, **params: Any) -> None:
                captured.append(dict(params))

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int, role: str | None = None) -> RestResponse: ...

        mocker.patch.object(Client, "request")
        instance = TestAPI(api_client)
        instance.get_customer(5)  # role not supplied

        assert captured == [{}]


class TestEndpointModelFieldDefaults:
    def test_endpoint_model_field_defaults(self, api_client: APIClient) -> None:
        """Test endpoint model field gets correct default value."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer_id}/orders/{order_id}")
            def get_item(
                self, customer_id: int, order_id: int = 1, name: str = "x", tag: str | None = None
            ) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_item.model
        fields = model.__dataclass_fields__

        assert fields["customer_id"].default is MISSING
        assert fields["customer_id"].metadata.get("path") is True
        assert fields["order_id"].default == 1
        assert fields["order_id"].metadata.get("path") is True
        assert fields["name"].default == "x"
        assert fields["name"].metadata == {}
        assert fields["tag"].default is None
        assert fields["tag"].metadata == {}

    def test_endpoint_model_no_default_body_param_gets_unset(self, api_client: APIClient) -> None:
        """Test that a body/query param with no signature default gets Unset in the model."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/items/{item_id}")
            def get_item(self, item_id: int, param1: str) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_item.model
        fields = model.__dataclass_fields__

        assert fields["item_id"].default is MISSING
        assert fields["param1"].default is Unset


class TestQueryMarkerRouting:
    """Tests for per-parameter Query marker routing behavior.

    A parameter annotated with Annotated[T, Query()], Annotated[T, Query] (bare class), or the legacy
    Annotated[T, "query"] on a non-GET endpoint must be sent as a URL query string, not in the request body.
    All three forms must produce identical behavior.
    """

    def _make_request_and_capture(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> dict[str, Any]:
        """Helper: call the single endpoint on api_class with mode='test' and return httpx call kwargs."""
        mock_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        instance.update_item(item_id=1, mode="test")
        return mock_request.call_args.kwargs

    @pytest.mark.parametrize("metadata", [Query(), Query, "query"])
    def test_query_marker_routes_to_query_string(
        self, mocker: MockerFixture, api_client: APIClient, metadata: Query | type[Query] | str
    ) -> None:
        """Test that Annotated[T, <query metadata>] sends the param as a URL query string on a non-GET endpoint."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, metadata] = Unset) -> RestResponse: ...

        kwargs = self._make_request_and_capture(mocker, api_client, TestAPI)

        assert kwargs.get("params") == {"mode": "test"}
        assert "mode" not in (kwargs.get("json") or {})

    def test_query_marker_routes_none_to_query_string(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an explicit None value for a Query-annotated param is sent as a query string param, not the body.

        None reaches the query string as an empty value (?mode=), preserving the Unset-vs-None
        distinction: Unset omits the param entirely; None sends it with an empty value.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, Query()] = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, mode=None)
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"mode": None}
        assert "mode" not in (kwargs.get("json") or {})

    def test_query_marker_routes_mismatched_type_to_query_string(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that a type-mismatched value for a Query-annotated param still routes to the query string.

        Routing follows the annotation, not the runtime value. This is intentional: the client
        is designed for negative testing and must allow deliberately wrong-typed values.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, Query()] = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, mode=123)  # int given for str-annotated Query param
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"mode": 123}
        assert "mode" not in (kwargs.get("json") or {})

    def test_alias_preserved_for_mismatched_type(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an Alias is applied even when the runtime value does not match the declared type.

        Alias resolution follows the annotation, not the runtime value.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                content_type: Annotated[str, Alias("Content-Type"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, content_type=123)  # int given for str-annotated param
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"Content-Type": 123}
        assert "content_type" not in (kwargs.get("json") or {})
        assert "Content-Type" not in (kwargs.get("json") or {})

    def test_union_annotated_picks_matching_variant(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a union of Annotated[] types picks the variant matching the given value's type."""
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                value: Annotated[str, Query()] | Annotated[int, Alias("n"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)

        # int value → Annotated[int, Alias("n"), Query()] selected → alias "n" applied
        instance.update_item(item_id=1, value=42)
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"n": 42}
        assert "value" not in (kwargs.get("json") or {})

        # str value → Annotated[str, Query()] selected → param name "value" kept
        instance.update_item(item_id=1, value="hello")
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"value": "hello"}

    def test_union_annotated_falls_back_to_first_variant_on_no_match(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that when no union variant matches, the first variant is used as a fallback.

        Routing must still happen (the param must reach the query string) even when the given value
        does not match any of the declared union variants.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                # First variant: Annotated[str, Query()] — will be selected as fallback
                # Second variant: Annotated[int, Alias("n"), Query()]
                value: Annotated[str, Query()] | Annotated[int, Alias("n"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)

        # list value matches neither str nor int → falls back to first variant → no alias, routed to query
        instance.update_item(item_id=1, value=[1, 2, 3])
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"value": [1, 2, 3]}
        assert "value" not in (kwargs.get("json") or {})


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
