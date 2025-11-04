from collections.abc import Generator
from pathlib import Path

import pytest
from common_libs.clients.rest_client import RestResponse
from pact import Pact, match

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.contract.consumer.helper import pact_mock_server

pytestmark = [pytest.mark.contracttest, pytest.mark.xdist_group("contract")]


@pytest.fixture
def pact(pacts_dir: Path) -> Generator[Pact]:
    pact = Pact("auth-consumer", "auth-provider").with_specification("V4")
    yield pact
    pact.write_file(pacts_dir)


def test_auth_login_contract(pact: Pact, unauthenticated_client: DemoAppAPIClient, fake_token: str) -> None:
    """Consumer contract test for the POST /v1/auth/login endpoint"""
    endpoint_func = unauthenticated_client.Auth.login
    expected_status_code = 201
    payload = {"username": "foo", "password": "bar"}
    response = {"token": match.str(fake_token)}

    (
        pact.upon_receiving("login request")
        .with_request(endpoint_func.method, endpoint_func.path)
        .with_body(body=payload, content_type="application/json")
        .will_respond_with(expected_status_code)
        .with_body(body=response, content_type="application/json")
    )

    with pact_mock_server(pact, unauthenticated_client):
        r = endpoint_func(**payload)
        assert isinstance(r, RestResponse)
        assert r.status_code == expected_status_code
        assert r.response["token"] == fake_token


def test_auth_logout_contract(pact: Pact, authenticated_client: DemoAppAPIClient) -> None:
    """Consumer contract test for the GET /v1/auth/logout endpoint"""
    endpoint_func = authenticated_client.Auth.logout
    expected_status_code = 200
    response = {"message": "logged out"}

    (
        pact.upon_receiving("logout request")
        .with_request(endpoint_func.method, endpoint_func.path)
        .will_respond_with(expected_status_code)
        .with_body(body=response, content_type="application/json")
    )

    with pact_mock_server(pact, authenticated_client):
        r = endpoint_func()
        assert isinstance(r, RestResponse)
        assert r.status_code == expected_status_code
        assert r.response["message"] == response["message"]
