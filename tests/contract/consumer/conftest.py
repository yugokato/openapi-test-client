import uuid
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from pact import Pact
from pact.pact import PactServer
from pytest import FixtureRequest, TempPathFactory

from openapi_test_client import logger
from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration.helper import DemoAppLifecycleManager, update_client_base_url


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


@pytest.fixture
def pact_factory(pacts_dir: Path) -> Callable[[str], AbstractContextManager[Pact]]:
    """Pact factory"""

    @contextmanager
    def create_pact(contract_name: str) -> Generator[Pact]:
        pact = Pact(f"{contract_name}-consumer", f"{contract_name}-provider").with_specification("V4")
        yield pact
        pact.write_file(pacts_dir)

    return create_pact


@pytest.fixture(scope="module")
def pact_server_factory(
    request: FixtureRequest, tmp_path_factory: TempPathFactory
) -> Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]]:
    """Pact server factory"""

    @contextmanager
    def create_pact_server(pact: Pact, client: DemoAppAPIClient) -> Generator[PactServer]:
        with DemoAppLifecycleManager(request, tmp_path_factory, start=False) as app_manager:
            assert app_manager.port is not None
            logger.debug("Starting Pact server...")
            moc_server = pact.serve(addr=app_manager.host, port=app_manager.port)
            with moc_server:
                app_manager._wait_for_app_to_start()
                update_client_base_url(client, app_manager.port)
                yield moc_server

    return create_pact_server
