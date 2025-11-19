import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from common_libs.clients.rest_client import AsyncRestClient

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration import helper

IS_TOX = os.environ.get("IS_TOX")


@pytest_asyncio.fixture
async def async_api_client(port: int) -> AsyncGenerator[DemoAppAPIClient]:
    """Async API client"""
    client = DemoAppAPIClient(async_mode=True)
    assert client.async_mode is True
    assert isinstance(client.rest_client, AsyncRestClient)
    if IS_TOX:
        helper.update_client_base_url(client, port)
    yield client
    await client.rest_client.aclose()
