"""Unit tests for endpoint.py"""

from __future__ import annotations

import pytest
from common_libs.clients.rest_client import RestResponse
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core import Endpoint, endpoint
from openapi_test_client.libraries.core.base import APIBase, APIClient

pytestmark = [pytest.mark.unittest]


class TestEndpointObject:
    """Tests for the Endpoint object attached to EndpointFunc"""

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_attrs(self, api_client: APIClient, api_class: type[APIBase], with_instance: bool) -> None:
        """Test that Endpoint has correct default field values"""
        if with_instance:
            ep = api_class(api_client).get_something.endpoint
        else:
            ep = api_class.get_something.endpoint
        assert ep.api_class is api_class
        assert ep.method == "get"
        assert ep.path == "/v1/something"
        assert ep.func_name == "get_something"
        if with_instance:
            assert ep.url == f"{api_client.base_url}{ep.path}"
        else:
            assert ep.url is None
        assert ep.content_type is None
        assert ep.is_public is False
        assert ep.is_documented is True
        assert ep.is_deprecated is False

    def test_str(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint.__str__ formats the method and path correctly"""

        ep = api_class.get_something.endpoint
        assert str(ep) == f"{ep.method.upper()} {ep.path}"

    def test_eq(self, api_class: type[APIBase]) -> None:
        """Test that endpoints with the same api_class, method, and path are equal regardless of func_name"""
        ep = api_class.get_something.endpoint
        other = Endpoint(
            api_class=ep.api_class,
            method=ep.method,
            path=ep.path,
            func_name="different_name",
            model=ep.model,
        )
        assert ep == other

    def test_eq_not_equal(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint objects with different method or path are not equal"""
        ep = api_class.get_something.endpoint

        different_path = Endpoint(
            api_class=ep.api_class,
            method=ep.method,
            path="/v1/other",
            func_name=ep.func_name,
            model=ep.model,
        )
        assert ep != different_path

        different_method = Endpoint(
            api_class=ep.api_class,
            method="post",
            path=ep.path,
            func_name=ep.func_name,
            model=ep.model,
        )
        assert ep != different_method

    def test_hash_is_stable_and_consistent(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint hash is stable (same value each call) and consistent between equal endpoints"""
        ep = api_class.get_something.endpoint
        other = Endpoint(
            api_class=ep.api_class,
            method=ep.method,
            path=ep.path,
            func_name="different_name",
            model=ep.model,
        )
        assert hash(ep) == hash(ep)
        assert ep == other
        assert hash(ep) == hash(other)

    def test_eq_different_api_class_not_equal(self, api_client: APIClient) -> None:
        """Test that endpoints with the same method and path on different API classes are not equal"""

        class API1(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/shared")
            def shared_endpoint(self) -> RestResponse: ...

        class API2(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/shared")
            def shared_endpoint(self) -> RestResponse: ...

        ep1 = API1.shared_endpoint.endpoint
        ep2 = API2.shared_endpoint.endpoint

        assert ep1 != ep2
        assert hash(ep1) != hash(ep2)

    def test_is_frozen(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint is a frozen dataclass and attributes cannot be modified"""
        ep = api_class.get_something.endpoint
        with pytest.raises(AttributeError, match="cannot assign to field"):
            ep.path = "/new/path"

    def test_endpoint_metadata_propagates(self, api_client: APIClient) -> None:
        """Test that endpoint metadata applied on an endpoint function propagates from endpoint handler to Endpoint"""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.undocumented
            @endpoint.is_public
            @endpoint.is_deprecated
            @endpoint.content_type("application/xml")
            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = TestAPI(api_client)
        ep = instance.get_something.endpoint

        assert ep.is_documented is False
        assert ep.is_public is True
        assert ep.is_deprecated is True
        assert ep.content_type == "application/xml"

    def test_class_level_endpoint_flag_propagates(self, api_client: APIClient) -> None:
        """Test that endpoint metadata applied on API class propagates from endpoint handler to Endpoint"""

        @endpoint.undocumented
        @endpoint.is_deprecated
        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = TestAPI(api_client)
        ep = instance.get_something.endpoint

        assert ep.is_documented is False
        assert ep.is_public is False
        assert ep.is_deprecated is True

    def test_endpoint_call(self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that Endpoint.__call__ makes the correct HTTP call and returns RestResponse in sync mode"""
        mock_httpx_request = mocker.patch.object(Client, "request")
        ep = api_class.get_something.endpoint
        r = ep(api_client)
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()

    async def test_endpoint_call_async(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that Endpoint.__call__ makes the correct HTTP call and returns RestResponse in async mode"""
        mock_httpx_request = mocker.patch.object(AsyncClient, "request")
        ep = api_class.get_something.endpoint
        r = await ep(api_client_async)
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()
