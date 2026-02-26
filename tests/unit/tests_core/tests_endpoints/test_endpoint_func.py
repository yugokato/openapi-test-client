"""Unit tests for endpoints_func.py"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import pytest
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import ResponseExt
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.endpoints import AsyncEndpointFunc, EndpointFunc, SyncEndpointFunc, endpoint
from openapi_test_client.libraries.core.endpoints.utils.endpoint_call import generate_rest_func_params
from openapi_test_client.libraries.core.types import EndpointModel

P = ParamSpec("P")
R = TypeVar("R")

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

    def test_endpoint_function_call(
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]
    ) -> None:
        """Test that endpoint function call (sync mode) makes an HTTP request and returns a RestResponse"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        r = instance.get_something()
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()

    async def test_endpoint_function_call_async(
        self, mocker: MockerFixture, api_client_async: OpenAPIClient, api_class: type[APIBase]
    ) -> None:
        """Test that endpoint function call (async mode) makes an HTTP request and returns a RestResponse"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")
        instance = api_class(api_client_async)
        r = await instance.get_something()
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()

    @pytest.mark.parametrize("with_hooks", [True, False])
    def test_endpoint_function_call_flow(
        self, mocker: MockerFixture, api_client: OpenAPIClient, with_hooks: bool
    ) -> None:
        """Test that endpoint function call is processed with endpoint decorators and request hooks and wrappers in the
        correct order
        """
        call_stack = []

        def mock_httpx_request_side_effect(*args: Any, **kwargs: Any) -> RestResponse:
            call_stack.append("call")
            mock_response = mocker.MagicMock(spec=ResponseExt)
            mock_response.status_code = 200
            return mock_response

        mock_httpx_request = mocker.patch.object(Client, "request", side_effect=mock_httpx_request_side_effect)

        @endpoint.decorator
        def deco1(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                call_stack.append("deco1_before")
                result = f(*args, **kwargs)
                call_stack.append("deco1_after")
                return result

            return wrapper

        @endpoint.decorator
        def deco2(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                call_stack.append("deco2_before")
                result = f(*args, **kwargs)
                call_stack.append("deco2_after")
                return result

            return wrapper

        class TestAPI(APIBase):
            """A fake API class with request hooks/wrappers"""

            TAGs = ("Test",)
            app_name = api_client.app_name

            def pre_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("pre_request")

            def post_request_hook(self, *args: Any, **kwargs: Any) -> None:
                call_stack.append("post_request")

            def request_wrapper(self) -> list[Callable[..., Any]]:
                def wrapper1(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper1_before")
                        result = f(*args, **kwargs)
                        call_stack.append("request_wrapper1_after")
                        return result

                    return wrapper

                def wrapper2(f: Callable[..., Any]) -> Callable[..., Any]:
                    @wraps(f)
                    def wrapper(*args: Any, **kwargs: Any) -> Any:
                        call_stack.append("request_wrapper2_before")
                        result = f(*args, **kwargs)
                        call_stack.append("request_wrapper2_after")
                        return result

                    return wrapper

                return [wrapper1, wrapper2]

            @deco1
            @deco2
            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                """A fake API function with decorators"""
                ...

        instance = TestAPI(api_client)
        assert call_stack == []
        instance.get_something(with_hooks=with_hooks)
        mock_httpx_request.assert_called_once()
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

    def test_custom_function_body_returning_rest_response(
        self, mocker: MockerFixture, api_client: OpenAPIClient
    ) -> None:
        """Test that when an endpoint function's custom body returns a RestResponse, it is used directly
        without falling through to the auto-generated request path (generate_rest_func_params not called)
        """
        mocker.patch.object(Client, "request")
        spy_generate = mocker.patch(f"{generate_rest_func_params.__module__}.{generate_rest_func_params.__name__}")

        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                # Custom body: explicitly calls the rest client and returns the response directly
                return self.api_client.rest_client._get("/v1/something")

        instance = TestAPI(api_client)
        r = instance.get_something()

        assert isinstance(r, RestResponse)
        spy_generate.assert_not_called()

    def test_custom_function_body_wrong_return_type(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that a custom endpoint body returning a non-RestResponse raises RuntimeError"""
        mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse:
                return "not a response"

        instance = TestAPI(api_client)
        with pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object, got str"):
            instance.get_something()
