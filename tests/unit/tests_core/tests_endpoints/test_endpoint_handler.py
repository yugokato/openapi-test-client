"""Unit tests for endpoint_handler.py"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.common.constants import VALID_METHODS
from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.endpoints import (
    AsyncEndpointFunc,
    EndpointFunc,
    EndpointHandler,
    SyncEndpointFunc,
    endpoint,
)

P = ParamSpec("P")
R = TypeVar("R")

pytestmark = [pytest.mark.unittest]


class TestEndpointHandlerGet:
    """Tests for EndpointHandler.__get__() descriptor protocol"""

    @pytest.fixture
    def api_class(self, api_client: OpenAPIClient) -> type[APIBase]:
        """Returns an API class with one fake endpoint function that doesn't have `@endpoint.<method>` decorator"""

        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            def get_something(self) -> RestResponse: ...

        return TestAPI

    @pytest.mark.parametrize("api_client", ["sync", "async"], indirect=True)
    @pytest.mark.parametrize("with_instance", [True, False])
    def test_returns_endpoint_func_instance(
        self, api_class: type[APIBase], api_client: OpenAPIClient, with_instance: bool
    ) -> None:
        """Test that __get__() returns an EndpointFunc instance based on the API client's sync/async mode"""
        endpoint_handler = EndpointHandler(api_class.get_something, "get", "/something")
        instance = api_class(api_client) if with_instance else None
        endpoint_func = endpoint_handler.__get__(instance, api_class)
        assert isinstance(endpoint_func, EndpointFunc)

        if with_instance:
            assert endpoint_func.api_client is api_client
            assert endpoint_func.rest_client is api_client.rest_client
        else:
            assert endpoint_func.api_client is None
            assert endpoint_func.rest_client is None

        if with_instance and api_client.async_mode:
            assert isinstance(endpoint_func, AsyncEndpointFunc)
        else:
            assert isinstance(endpoint_func, SyncEndpointFunc)

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_caches_endpoint_func_per_key(
        self, api_class: type[APIBase], api_client: OpenAPIClient, with_instance: bool
    ) -> None:
        """Test that __get__() returns the same cached EndpointFunc on repeated calls with same key"""
        handler = EndpointHandler(api_class.get_something, "get", "/something")
        instance = api_class(api_client) if with_instance else None

        result1 = handler.__get__(instance, api_class)
        result2 = handler.__get__(instance, api_class)

        assert result1 is result2

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_cache_key_is_func_name_instance_owner(
        self, api_class: type[APIBase], api_client: OpenAPIClient, with_instance: bool
    ) -> None:
        """Test that __get__() stores results using (func_name, instance, owner) as cache key"""
        handler = EndpointHandler(api_class.get_something, "get", "/something")
        instance = api_class(api_client) if with_instance else None
        handler.__get__(instance, api_class)

        expected_key = (api_class.get_something.__name__, instance, api_class)
        assert expected_key in EndpointHandler._endpoint_functions

    def test_non_api_base_owner_raises_not_implemented(self) -> None:
        """Test that passing a non-APIBase class as owner raises NotImplementedError"""

        class NonAPIClass: ...

        def get_something(self: Any) -> RestResponse: ...

        handler = EndpointHandler(get_something, "get", "/something")

        with pytest.raises(NotImplementedError, match="Unsupported API class"):
            handler.__get__(None, NonAPIClass)

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_endpoint_func_class_name_follows_convention(
        self, api_class: type[APIBase], api_client: OpenAPIClient, with_instance: bool
    ) -> None:
        """Test that EndpointFunc class name follows <APIClassName><FuncName>EndpointFunc format"""
        handler = EndpointHandler(api_class.get_something, "get", "/something")
        instance = api_class(api_client) if with_instance else None
        result = handler.__get__(instance, api_class)

        assert type(result).__name__ == "TestAPIGetSomethingEndpointFunc"


class TestRegisterDecorator:
    """Tests for EndpointHandler.register_decorator() and decorators property"""

    def test_decorators_is_empty_list_by_default(self) -> None:
        """Test that EndpointHandler.decorators returns empty list by default"""

        def get_something(self: Any) -> RestResponse: ...

        handler = EndpointHandler(get_something, "get", "/something")
        assert handler.decorators == []

    def test_register_single_decorator(self) -> None:
        """Test that register_decorator() adds a single decorator to the list"""

        def get_something(self: Any) -> RestResponse: ...

        handler = EndpointHandler(get_something, "get", "/something")

        def decorator(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        handler.register_decorator(decorator)
        assert handler.decorators == [decorator]

    def test_register_multiple_decorators_at_once(self) -> None:
        """Test that register_decorator() can register multiple decorators in a single call"""

        def get_something(self: Any) -> RestResponse: ...

        handler = EndpointHandler(get_something, "get", "/something")

        def deco1(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        def deco2(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        handler.register_decorator(deco1, deco2)
        assert handler.decorators == [deco1, deco2]


class TestEndpointHandlerViaEndpointFactory:
    """Tests for EndpointHandler created via @endpoint.<method>() endpoint factory"""

    @pytest.mark.parametrize("method", VALID_METHODS)
    def test_handler_created_by_endpoint_factory(self, method: str) -> None:
        """Test that @endpoint.<method>() creates a properly configured EndpointHandler"""

        endpoint_factory = getattr(endpoint, method)

        @endpoint_factory("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        endpoint_handler = do_something
        assert isinstance(endpoint_handler, EndpointHandler)
        assert endpoint_handler.method == method
        assert endpoint_handler.path == "/v1/something"
        assert endpoint_handler.use_query_string is (method == "get")
        assert endpoint_handler.is_public is False
        assert endpoint_handler.is_documented is True
        assert endpoint_handler.is_deprecated is False
        assert endpoint_handler.content_type is None
        assert endpoint_handler.decorators == []

    def test_metadata_flags_applied_via_chained_decorators(self) -> None:
        """Test that chained metadata decorators correctly set multiple flags"""

        @endpoint.undocumented
        @endpoint.is_deprecated
        @endpoint.is_public
        @endpoint.content_type("application/octet-stream")
        @endpoint.get("/v1/something")
        def get_something(self: Any) -> RestResponse: ...

        assert get_something.is_documented is False
        assert get_something.is_deprecated is True
        assert get_something.is_public is True
        assert get_something.content_type == "application/octet-stream"
