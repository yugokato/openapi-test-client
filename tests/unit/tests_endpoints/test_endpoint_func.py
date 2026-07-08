"""Unit tests for OpenAPI-specific endpoint function behavior."""

from __future__ import annotations

import api_client_core.endpoints.utils.endpoint_call as endpoint_call_util
import pytest
from common_libs.clients.rest_client import RestResponse
from httpx import Client
from pytest_mock import MockerFixture

from openapi_test_client.libraries import EndpointFunc, endpoint
from openapi_test_client.libraries.base import OpenAPIBase, OpenAPIClient
from openapi_test_client.libraries.types import Unset

pytestmark = [pytest.mark.unittest]


class TestOpenAPIEndpointFunc:
    """Tests for OpenAPI EndpointFunc.docs() and get_usage() helpers"""

    def test_docs_with_api_spec(
        self,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        api_class: type[OpenAPIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that docs() prints the api_spec usage string when the endpoint is documented"""
        usage_text = "GET /v1/something\n  Summary: Get something"
        mock_spec = mocker.MagicMock()
        mock_spec.get_endpoint_usage.return_value = usage_text
        mocker.patch.object(api_client, "api_spec", mock_spec)

        instance = api_class(api_client)
        instance.get_something.docs()

        captured = capsys.readouterr()
        assert usage_text in captured.out

    def test_docs_without_api_spec(
        self,
        mocker: MockerFixture,
        api_client: OpenAPIClient,
        api_class: type[OpenAPIBase],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test that docs() prints 'Docs not available' when api_spec returns None for the endpoint"""
        mock_spec = mocker.MagicMock()
        mock_spec.get_endpoint_usage.return_value = None
        mocker.patch.object(api_client, "api_spec", mock_spec)

        instance = api_class(api_client)
        instance.get_something.docs()

        captured = capsys.readouterr()
        assert "Docs not available" in captured.out

    def test_get_usage_returns_none_when_undocumented(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that get_usage() returns None when the endpoint is marked undocumented"""

        class UndocumentedAPI(OpenAPIBase):
            TAGs = ("Test",)
            app_name = api_client.app_name

            @endpoint.undocumented
            @endpoint.get("/v1/hidden")
            def get_hidden(self) -> RestResponse: ...

        instance = UndocumentedAPI(api_client)
        endpoint_func = instance.get_hidden
        assert isinstance(endpoint_func, EndpointFunc)
        assert endpoint_func.get_usage() is None

    def test_get_usage_returns_none_without_api_spec(
        self, mocker: MockerFixture, api_client: OpenAPIClient, api_class: type[OpenAPIBase]
    ) -> None:
        """Test that get_usage() returns None when the client has no api_spec attribute"""
        mocker.patch.object(api_client, "api_spec", None)

        instance = api_class(api_client)
        assert instance.get_something.get_usage() is None


class TestOpenAPIUnsetFilter:
    """Tests for OpenAPI-specific Unset-exclusion behavior in endpoint payloads.

    OpenAPI-side endpoints (OpenAPIBase) exclude any parameter whose signature default
    is the Unset sentinel, because filter_payload_params() drops Unset-valued entries
    before they reach generate_rest_func_params.
    """

    def test_openapi_unset_defaults_excluded_from_payload(
        self, mocker: MockerFixture, api_client: OpenAPIClient
    ) -> None:
        """Test that OpenAPI endpoints with Unset defaults produce an empty payload when called with no args."""
        mocker.patch.object(Client, "request")
        spy_generate = mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

        class OpenAPIStyleAPI(OpenAPIBase):
            TAGs = ("Items",)
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = Unset, count: int = Unset) -> RestResponse: ...

        instance = OpenAPIStyleAPI(api_client)
        instance.create_item()

        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {}

    def test_openapi_explicit_params_pass_through(self, mocker: MockerFixture, api_client: OpenAPIClient) -> None:
        """Test that explicitly-supplied non-Unset params pass through to the payload in OpenAPI mode."""
        mocker.patch.object(Client, "request")
        spy_generate = mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

        class OpenAPIStyleAPI(OpenAPIBase):
            TAGs = ("Items",)
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = Unset, count: int = Unset) -> RestResponse: ...

        instance = OpenAPIStyleAPI(api_client)
        instance.create_item(name="alice")

        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {"name": "alice"}
