from collections.abc import Generator

import pytest
from pytest import FixtureRequest, TempPathFactory

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration.helper import DemoAppLifecycleManager, update_client_base_url


@pytest.fixture(scope="module", autouse=True)
def demo_app_server(request: FixtureRequest, tmp_path_factory: TempPathFactory) -> Generator[DemoAppLifecycleManager]:
    """Start demo app with dynamically selected port"""
    with DemoAppLifecycleManager(request, tmp_path_factory) as app_manager:
        yield app_manager


@pytest.fixture(scope="module")
def host(demo_app_server: DemoAppLifecycleManager) -> str:
    """Host of the demo app"""
    return demo_app_server.host


@pytest.fixture(scope="module")
def port(demo_app_server: DemoAppLifecycleManager) -> int:
    """Port of the demo app"""
    assert demo_app_server.port is not None
    return demo_app_server.port


@pytest.fixture(scope="module")
def token(port: int) -> Generator[str]:
    """Valid auth token"""
    client = DemoAppAPIClient()
    update_client_base_url(client, port)
    r = client.Auth.login(username="foo", password="bar")
    assert r.ok
    yield client.rest_client.get_bearer_token()
    r = client.Auth.logout()
    assert r.ok
