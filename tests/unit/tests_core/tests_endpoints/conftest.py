from collections.abc import Callable

import pytest
from common_libs.clients.rest_client import AsyncRestClient, RestClient, RestResponse
from httpx import AsyncClient, Client
from pytest import FixtureRequest
from pytest_mock import MockerFixture

from openapi_test_client.clients.openapi import OpenAPIClient
from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.endpoints import EndpointHandler, endpoint


@pytest.fixture(scope="session")
def api_client_factory(session_mocker: MockerFixture) -> Callable[..., OpenAPIClient]:
    """Test API client factory"""

    def create(async_mode: bool = False) -> OpenAPIClient:
        rest_client: RestClient | AsyncRestClient
        if async_mode:
            session_mocker.patch.object(AsyncClient, "request")
            rest_client = AsyncRestClient("https://example.com/api")
        else:
            session_mocker.patch.object(Client, "request")
            rest_client = RestClient("https://example.com/api")

        return OpenAPIClient("test", "/docs", rest_client=rest_client, async_mode=async_mode)

    return create


@pytest.fixture
def api_client(request: FixtureRequest, api_client_factory: Callable[..., OpenAPIClient]) -> OpenAPIClient:
    """A general API client for testing, with support for async mode via test parameterization"""
    if hasattr(request, "param"):
        mode = request.param
        assert mode in ["sync", "async"], "Invalid mode parameter, must be 'sync' or 'async'"
        is_async = mode == "async"
        return api_client_factory(async_mode=is_async)
    return api_client_factory()


@pytest.fixture(scope="session")
def api_client_async(api_client_factory: Callable[..., OpenAPIClient]) -> OpenAPIClient:
    """A general API client for testing (async)"""
    return api_client_factory(async_mode=True)


@pytest.fixture
def api_class(api_client: OpenAPIClient) -> type[APIBase]:
    """Returns a testable API class with one endpoint function"""

    class TestAPI(APIBase):
        TAGs = ("Test",)
        app_name = api_client.app_name

        @endpoint.get("/v1/something")
        def get_something(self) -> RestResponse: ...

    return TestAPI


@pytest.fixture(autouse=True)
def clear_cache(mocker: MockerFixture) -> None:
    mocker.patch.dict(EndpointHandler._endpoint_functions, {}, clear=True)
