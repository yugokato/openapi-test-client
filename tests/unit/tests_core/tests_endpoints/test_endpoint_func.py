"""Unit tests for endpoints_func.py"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import wraps
from typing import Any

import pytest
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import ResponseExt
from httpx import AsyncClient, Client, ConnectError, HTTPError, Request
from pytest_mock import MockerFixture

from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.core import Endpoint
from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.endpoints import AsyncEndpointFunc, EndpointFunc, SyncEndpointFunc, endpoint
from openapi_test_client.libraries.core.endpoints.utils.endpoint_call import generate_rest_func_params
from openapi_test_client.libraries.core.types import EndpointModel

pytestmark = [pytest.mark.unittest]


class TestEndpointFunc:
    """Tests for core EndpointFunc behavior"""

    @pytest.mark.parametrize("api_client", ["sync", "async"], indirect=True)
    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_func_access(self, api_client: OpenAPIClient, api_class: type[APIBase], access_by: str) -> None:
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

    def test_repr(self, api_client: OpenAPIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.__repr__ contains 'mapped to' reference to original function"""
        instance = api_class(api_client)
        repr_str = repr(instance.get_something)

        assert "mapped to" in repr_str

    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_property_returns_endpoint_object(
        self, api_client: OpenAPIClient, api_class: type[APIBase], access_by: str
    ) -> None:
        """Test that EndpointFunc.endpoint returns an Endpoint object"""
        if access_by == "instance":
            api_class_or_instance = api_class(api_client)
        else:
            api_class_or_instance = api_class
        endpoint = api_class_or_instance.get_something.endpoint
        assert isinstance(endpoint, Endpoint)

    def test_model_property_returns_endpoint_model(self, api_client: OpenAPIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.model returns a subclass of EndpointModel"""

        instance = api_class(api_client)
        endpoint_func = instance.get_something
        endpoint_model = endpoint_func.model

        assert issubclass(endpoint_model, EndpointModel)

    def test_model_property_name(self, api_client: OpenAPIClient, api_class: type[APIBase]) -> None:
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
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]
    ) -> None:
        """Test that SyncEndpointFunc.__call__ returns a RestResponse"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        r = instance.get_something()
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()

    def test_sync_call_uses_sync_executor(
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]
    ) -> None:
        """Test that SyncEndpointFunc uses SyncExecutor to execute the HTTP request"""
        from openapi_test_client.libraries.core.endpoints.executors import SyncExecutor

        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, SyncEndpointFunc)
        assert isinstance(endpoint_func.executor, SyncExecutor)

        instance.get_something()
        mock_httpx_request.assert_called_once()

    def test_sync_call_invokes_pre_and_post_hooks(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that pre_request_hook and post_request_hook are called during sync execution"""
        call_stack: list[str] = []

        def mock_httpx_side_effect(*args: Any, **kwargs: Any) -> ResponseExt:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mocker.patch.object(Client, "request", side_effect=mock_httpx_side_effect)

        class HookedAPI(APIBase):
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client: OpenAPIClient, with_hooks: bool
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
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client: OpenAPIClient
    ) -> None:
        """Test that a custom sync endpoint body returning RestResponse bypasses auto-generated request path"""
        mocker.patch.object(Client, "request")
        spy_generate = mocker.patch(f"{generate_rest_func_params.__module__}.{generate_rest_func_params.__name__}")

        class SyncCustomAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return self.api_client.rest_client._get("/v1/something")

        instance = SyncCustomAPI(api_client)
        r = instance.get_something()

        assert isinstance(r, RestResponse)
        spy_generate.assert_not_called()

    def test_sync_call_with_custom_body_wrong_return_type(
        self, mocker: MockerFixture, api_client: OpenAPIClient
    ) -> None:
        """Test that a custom sync endpoint body returning a non-RestResponse raises RuntimeError"""
        mocker.patch.object(Client, "request")

        class SyncBadReturnAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return "not a response"

        instance = SyncBadReturnAPI(api_client)
        with pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object, got str"):
            instance.get_something()

    def test_sync_call_http_error_propagates(
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]
    ) -> None:
        """Test that HTTPError raised during sync execution propagates to the caller"""
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("connection error")
        connect_error.request = mock_request
        mocker.patch.object(Client, "request", side_effect=connect_error)
        instance = api_class(api_client)
        with pytest.raises(HTTPError, match="connection error"):
            instance.get_something()

    def test_sync_call_http_error_still_runs_post_hook(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that post_request_hook is still called even when an HTTPError occurs in sync mode"""
        post_hook_called = False
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("timeout")
        connect_error.request = mock_request

        mocker.patch.object(Client, "request", side_effect=connect_error)

        class HookedAPI(APIBase):
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]
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

    def test_sync_call_uses_endpoint_path(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that the sync endpoint call uses the configured endpoint path"""
        mock_httpx_request = mocker.patch.object(Client, "request")

        class PathAPI(APIBase):
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that AsyncEndpointFunc.__call__ returns a RestResponse when awaited"""
        mocker.patch.object(AsyncClient, "request")
        instance = api_class_async(api_client_async)
        r = await instance.get_something()
        assert isinstance(r, RestResponse)

    async def test_async_call_uses_async_executor(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that AsyncEndpointFunc uses AsyncExecutor to execute the HTTP request"""
        from openapi_test_client.libraries.core.endpoints.executors import AsyncExecutor

        mock_httpx_request = mocker.patch.object(AsyncClient, "request")
        instance = api_class_async(api_client_async)
        endpoint_func = instance.get_something

        assert isinstance(endpoint_func, AsyncEndpointFunc)
        assert isinstance(endpoint_func.executor, AsyncExecutor)

        await instance.get_something()
        mock_httpx_request.assert_called_once()

    async def test_async_call_invokes_pre_and_post_hooks(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient
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
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, with_hooks: bool
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
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client_async: OpenAPIClient
    ) -> None:
        """Test that a custom async endpoint body returning RestResponse bypasses auto-generated request path"""
        mocker.patch.object(AsyncClient, "request")
        spy_generate = mocker.patch(f"{generate_rest_func_params.__module__}.{generate_rest_func_params.__name__}")

        class AsyncCustomAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client_async.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return self.api_client.rest_client._get("/v1/something")

        instance = AsyncCustomAPI(api_client_async)
        r = await instance.get_something()

        assert isinstance(r, RestResponse)
        spy_generate.assert_not_called()

    async def test_async_call_with_custom_body_wrong_return_type(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient
    ) -> None:
        """Test that a custom async endpoint body returning non-RestResponse raises RuntimeError"""
        mocker.patch.object(AsyncClient, "request")

        class AsyncBadReturnAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client_async.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return "not a response"

        instance = AsyncBadReturnAPI(api_client_async)
        with pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object, got str"):
            await instance.get_something()

    async def test_async_call_http_error_propagates(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, api_class_async: type[APIBase]
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
        self, mocker: MockerFixture, api_client_async: OpenAPIClient
    ) -> None:
        """Test that post_request_hook is still called even when an HTTPError occurs in async mode"""
        post_hook_called = False
        mock_request = mocker.MagicMock(spec=Request)
        connect_error = ConnectError("timeout")
        connect_error.request = mock_request

        mocker.patch.object(AsyncClient, "request", side_effect=connect_error)

        class HookedAPI(APIBase):
            TAGs = ("Test",)
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
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, api_class_async: type[APIBase]
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

    async def test_async_call_uses_endpoint_path(self, mocker: MockerFixture, api_client_async: OpenAPIClient) -> None:
        """Test that the async endpoint call uses the configured endpoint path"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")

        class PathAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client_async.app_name

            @endpoint.get("/v1/items")
            def get_items(self) -> RestResponse: ...

        instance = PathAPI(api_client_async)
        await instance.get_items()

        call_args = mock_httpx_request.call_args
        assert call_args.args == ("GET", "/v1/items")
