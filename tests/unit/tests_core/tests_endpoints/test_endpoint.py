"""Unit tests for endpoint.py"""

from __future__ import annotations

import pytest
from common_libs.clients.rest_client import RestResponse
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.core import APIBase, Endpoint, endpoint


class TestEndpointObject:
    """Tests for the Endpoint object attached to EndpointFunc"""

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_attrs(self, api_client: OpenAPIClient, api_class: type[APIBase], with_instance: bool) -> None:
        """Test that Endpoint has correct default field values"""
        if with_instance:
            ep = api_class(api_client).get_something.endpoint
        else:
            ep = api_class.get_something.endpoint
        assert ep.tags == ("Test",)
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
        """Test that endpoints with same method+path are equal regardless of other fields"""
        ep = api_class.get_something.endpoint
        other = Endpoint(
            tags=("Other",),
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
            tags=ep.tags,
            api_class=ep.api_class,
            method=ep.method,
            path="/v1/other",
            func_name=ep.func_name,
            model=ep.model,
        )
        assert ep != different_path

        different_method = Endpoint(
            tags=ep.tags,
            api_class=ep.api_class,
            method="post",
            path=ep.path,
            func_name=ep.func_name,
            model=ep.model,
        )
        assert ep != different_method

    def test_hash_matches_str_hash(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint hash matches hash of its str representation"""
        ep = api_class.get_something.endpoint
        assert hash(ep) == hash(str(ep))

    def test_is_frozen(self, api_class: type[APIBase]) -> None:
        """Test that Endpoint is a frozen dataclass and attributes cannot be modified"""
        ep = api_class.get_something.endpoint
        with pytest.raises(AttributeError, match="cannot assign to field"):
            ep.path = "/new/path"

    def test_endpoint_metadata_propagates(self, api_client: OpenAPIClient) -> None:
        """Test that endpoint metadata applied on an endpoint function propagates from endpoint handler to Endpoint"""

        class TestAPI(APIBase):
            TAGs = ("Test",)
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

    def test_class_level_endpoint_flag_propagates(self, api_client: OpenAPIClient) -> None:
        """Test that endpoint metadata applied on API class propagates from endpoint handler to Endpoint"""

        @endpoint.undocumented
        @endpoint.is_deprecated
        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        instance = TestAPI(api_client)
        ep = instance.get_something.endpoint

        assert ep.is_documented is False
        assert ep.is_public is False
        assert ep.is_deprecated is True

    @pytest.mark.parametrize("api_client", ["sync", "async"], indirect=True)
    def test_endpoint_call(self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[APIBase]) -> None:
        """Test that Endpoint.__call__ makes the correct HTTP call and returns RestResponse in sync/async mode"""
        if api_client.async_mode:
            httpx_client_class = AsyncClient
        else:
            httpx_client_class = Client

        mock_httpx_request = mocker.patch.object(httpx_client_class, "request")
        ep = api_class.get_something.endpoint
        r = ep(api_client)
        assert isinstance(r, RestResponse)
        mock_httpx_request.assert_called_once()
