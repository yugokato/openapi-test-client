import uuid

import pytest

from openapi_test_client.clients.demo_app import DemoAppAPIClient


@pytest.fixture(scope="module")
def fake_token() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def unauthenticated_client() -> DemoAppAPIClient:
    return DemoAppAPIClient()


@pytest.fixture
def authenticated_client(unauthenticated_client: DemoAppAPIClient, fake_token: str) -> DemoAppAPIClient:
    unauthenticated_client.rest_client.set_bearer_token(fake_token)
    return unauthenticated_client
