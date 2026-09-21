"""Unit tests for OpenAPI-specific endpoint behavior."""

from __future__ import annotations

from typing import Annotated

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.libraries import AsyncEndpointFunc, Endpoint, SyncEndpointFunc, endpoint
from openapi_test_client.libraries.base import BaseOpenAPI, OpenAPIClient
from openapi_test_client.libraries.types import Optional, Query, Unset

pytestmark = [pytest.mark.unittest]


class TestOpenAPIEndpointObject:
    """Tests for OpenAPI-specific Endpoint fields and behavior"""

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_openapi_attrs(self, api_client: OpenAPIClient, api_class: type[BaseOpenAPI], with_instance: bool) -> None:
        """Test that OpenAPIEndpoint has a tags field populated from the class TAGs"""

        if with_instance:
            ep = api_class(api_client).get_something.endpoint
        else:
            ep = api_class.get_something.endpoint
        assert isinstance(ep, Endpoint)
        assert ep.tags == ("Test",)


class TestOpenAPIEndpointBind:
    """Tests for `Endpoint.bind()` returning this project's OpenAPI endpoint-function subclasses"""

    def test_bind_returns_sync_endpoint_func(self, api_client: OpenAPIClient, api_class: type[BaseOpenAPI]) -> None:
        """Test that bind() returns this project's SyncEndpointFunc subclass, not the core one"""
        ep = api_class.get_something.endpoint
        bound = ep.bind(api_client)
        assert isinstance(bound, SyncEndpointFunc)
        assert bound.endpoint == ep

    def test_bind_returns_async_endpoint_func(
        self, api_client_async: OpenAPIClient, api_class_async: type[BaseOpenAPI]
    ) -> None:
        """Test that bind() returns this project's AsyncEndpointFunc subclass for an async client"""
        ep = api_class_async.get_something.endpoint
        bound = ep.bind(api_client_async)
        assert isinstance(bound, AsyncEndpointFunc)
        assert bound.endpoint == ep


class TestOpenAPIEndpointIterParams:
    """Tests for `EndpointIntrospection.iter_params()` reflecting OpenAPI-specific model construction"""

    def test_resolves_a_field_aliased_by_the_openapi_sanitizer(self, api_client: OpenAPIClient) -> None:
        """Test that iter_params() resolves a field renamed by the richer OpenAPI field-name sanitizer
        (a param named after an OpenAPI annotation type, e.g. `Format`) back to its signature name
        """

        class ItemsAPI(BaseOpenAPI):
            TAGs = ("Items",)
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, Format: str = Unset) -> RestResponse: ...

        ep = ItemsAPI.create_item.endpoint
        assert "Format_" in ep.model.__dataclass_fields__
        assert {p.name for p in ep.introspection.iter_params()} == {"Format"}

    def test_location_is_query_for_a_query_annotated_param_on_a_post_endpoint(self, api_client: OpenAPIClient) -> None:
        """Test that location is 'query' for a Query()-annotated param on a POST endpoint, and 'body' for
        a plain sibling param
        """

        class ItemsAPI(BaseOpenAPI):
            TAGs = ("Items",)
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(
                self, *, name: Annotated[Optional[str], Query()] = Unset, description: Optional[str] = Unset
            ) -> RestResponse: ...

        ep = ItemsAPI.create_item.endpoint
        params = {p.name: p for p in ep.introspection.iter_params()}
        assert params["name"].location == "query"
        assert params["description"].location == "body"
