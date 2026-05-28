from collections.abc import Callable

import pytest
from common_libs.clients.rest_client import AsyncRestClient, RestClient
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core.base.api_client import APIClient


@pytest.fixture(scope="module")
def api_client_factory(session_mocker: MockerFixture) -> Callable[..., APIClient]:
    """Core API client factory"""

    def create(async_mode: bool = False) -> APIClient:
        base_url = "https://example.com/api"
        rest_client: RestClient | AsyncRestClient
        if async_mode:
            session_mocker.patch.object(AsyncClient, "request")
            rest_client = AsyncRestClient(base_url)
        else:
            session_mocker.patch.object(Client, "request")
            rest_client = RestClient(base_url)
        return APIClient("test", rest_client=rest_client, async_mode=async_mode)

    return create
