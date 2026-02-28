from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest
from common_libs.clients.rest_client import RestResponse
from pact import Pact, match
from pact.pact import PactServer

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.contracttest, pytest.mark.xdist_group("contract")]


def test_create_user_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    authenticated_client: DemoAppAPIClient,
    fake_token: str,
) -> None:
    """Consumer contract test for the POST /v1/users endpoint"""
    endpoint_func = authenticated_client.Users.create_user
    expected_status_code = 201
    payload = {"first_name": "first_name", "last_name": "last_name", "email": "user@demo.app.net", "role": "admin"}
    response = {
        "id": match.int(1),
        "first_name": match.str("first_name"),
        "last_name": match.str("last_name"),
        "email": match.str("user@demo.app.net"),
        "role": match.str("admin"),
        "metadata": None,
    }

    with pact_factory("user") as pact:
        (
            pact.upon_receiving("POST user request")
            .with_request(endpoint_func.method, endpoint_func.path)
            .with_header("Authorization", f"Bearer {fake_token}")
            .with_body(body=payload, content_type="application/json")
            .will_respond_with(expected_status_code)
            .with_body(body=response, content_type="application/json")
        )

        with pact_server_factory(pact, authenticated_client):
            r = endpoint_func(**payload)
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
            assert r.response["first_name"] == payload["first_name"]


def test_get_user_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    authenticated_client: DemoAppAPIClient,
) -> None:
    """Consumer contract test for the  GET /v1/users/<user_id> endpoint"""
    user_id = 1
    endpoint_func = authenticated_client.Users.get_user
    expected_status_code = 200
    response = {
        "id": match.int(user_id),
        "first_name": match.str(f"first_name_{user_id}"),
        "last_name": match.str(f"last_name_{user_id}"),
        "email": match.str(f"user{user_id}@demo.app.net"),
        "metadata": None,
    }

    with pact_factory("user") as pact:
        (
            pact.upon_receiving("GET user request")
            .given(
                "the user exists",
                id=user_id,
                first_name=f"first_name_{user_id}",
                last_name=f"last_name_{user_id}",
            )
            .with_request(endpoint_func.method, endpoint_func.path.format(user_id=user_id))
            .will_respond_with(expected_status_code)
            .with_body(body=response, content_type="application/json")
        )

        with pact_server_factory(pact, authenticated_client):
            r = endpoint_func(user_id)
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
            assert r.response["id"] == user_id


def test_get_users_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    authenticated_client: DemoAppAPIClient,
) -> None:
    """Consumer contract test for the  GET /v1/users endpoint"""
    user_id = 1
    endpoint_func = authenticated_client.Users.get_users
    expected_status_code = 200
    response = match.each_like(
        {
            "id": match.int(user_id),
            "first_name": match.str(f"first_name_{user_id}"),
            "last_name": match.str(f"last_name_{user_id}"),
            "email": match.str(f"user{user_id}@demo.app.net"),
            "metadata": None,
        }
    )

    with pact_factory("user") as pact:
        (
            pact.upon_receiving("GET users request")
            .with_request(endpoint_func.method, endpoint_func.path)
            .will_respond_with(expected_status_code)
            .with_body(body=response, content_type="application/json")
        )

        with pact_server_factory(pact, authenticated_client):
            r = endpoint_func()
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
            assert len(r.response) > 0


def test_delete_user_contract(
    pact_factory: Callable[[str], AbstractContextManager[Pact]],
    pact_server_factory: Callable[[Pact, DemoAppAPIClient], AbstractContextManager[PactServer]],
    authenticated_client: DemoAppAPIClient,
) -> None:
    """Consumer contract test for the  DELETE /v1/users/{user_id} endpoint"""
    user_id = 10
    expected_status_code = 200
    endpoint_func = authenticated_client.Users.delete_user

    with pact_factory("user") as pact:
        (
            pact.upon_receiving("DELETE user request")
            .given(
                "the user exists",
                id=user_id,
                first_name=f"first_name_{user_id}",
                last_name=f"last_name_{user_id}",
            )
            .with_request(endpoint_func.method, endpoint_func.path.format(user_id=user_id))
            .will_respond_with(expected_status_code)
        )

        with pact_server_factory(pact, authenticated_client):
            r = endpoint_func(user_id)
            assert isinstance(r, RestResponse)
            assert r.status_code == expected_status_code
