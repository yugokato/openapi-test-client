from collections.abc import Generator
from contextlib import contextmanager

from common_libs.lock import Lock
from common_libs.network import find_open_port
from pact import Pact

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration.helper import update_client_base_url


@contextmanager
def pact_mock_server(pact: Pact, client: DemoAppAPIClient) -> Generator[None]:
    """Serve mock server for pact with dynamically selected port"""
    with Lock("pact_server"):
        port = find_open_port()
        with pact.serve(addr="127.0.0.1", port=port):
            update_client_base_url(client, port)
            yield
