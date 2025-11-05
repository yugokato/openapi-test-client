from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest
from common_libs.clients.rest_client import RestResponse
from pact import Pact, match
from pact.pact import PactServer

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.contracttest, pytest.mark.xdist_group("contract")]


def test_auth_login_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    unauthenticated_client: DemoAppAPIClient,
    fake_token: str,
) -> None:
    """Consumer contract test for the POST /v1/auth/login endpoint"""
    endpoint_func = unauthenticated_client.Auth.login
    expected_status_code = 201
    payload = {"username": "foo", "password": "bar"}
    response = {"token": match.str(fake_token)}

    with pact_factory("auth") as pact:
        (
            pact.upon_receiving("login request")
            .with_request(endpoint_func.method, endpoint_func.path)
            .with_body(body=payload, content_type="application/json")
            .will_respond_with(expected_status_code)
            .with_body(body=response, content_type="application/json")
        )

        with pact_server_factory(pact, unauthenticated_client):
            r = endpoint_func(**payload)
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
            assert r.response["token"] == fake_token


def test_auth_logout_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    authenticated_client: DemoAppAPIClient,
) -> None:
    """Consumer contract test for the GET /v1/auth/logout endpoint"""
    endpoint_func = authenticated_client.Auth.logout
    expected_status_code = 200
    response = {"message": "logged out"}

    with pact_factory("auth") as pact:
        (
            pact.upon_receiving("logout request")
            .with_request(endpoint_func.method, endpoint_func.path)
            .will_respond_with(expected_status_code)
            .with_body(body=response, content_type="application/json")
        )

        with pact_server_factory(pact, authenticated_client):
            r = endpoint_func()
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
            assert r.response["message"] == response["message"]
