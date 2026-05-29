import pytest

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration import helper

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.parametrize("validation_mode", [False, True])
def test_auth_login(unauthenticated_api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of Auth login API"""
    r = unauthenticated_api_client.Auth.login(username="foo", password="bar", validate=validation_mode)
    assert r.ok
    assert set(r.response.keys()) == {"token"}

    # The client's post-request hook should automatically set the token
    assert unauthenticated_api_client.rest_client.get_bearer_token() == r.response["token"]


def test_auth_logout(authenticated_api_client: DemoAppAPIClient) -> None:
    """Check basic client/server functionality of Auth logout API"""
    r = authenticated_api_client.Auth.logout()
    assert r.ok
    assert r.response["message"] == "logged out"

    # The client's post-request hook should automatically unset the token
    assert authenticated_api_client.rest_client.get_bearer_token() is None


def test_auth_logout_invalidates_token(authenticated_api_client: DemoAppAPIClient) -> None:
    """Test that logout API properly invalidates token"""
    # Skip the post-request hook to keep the bear token after logout
    r = authenticated_api_client.Auth.logout(with_hooks=False)
    assert r.ok
    assert r.response["message"] == "logged out"
    assert authenticated_api_client.rest_client.get_bearer_token() is not None

    # Call logout() again with the invalidated token
    r = authenticated_api_client.Auth.logout()
    assert r.status_code == 401
    assert r.response["error"]["message"] == "Login required"


@pytest.mark.parametrize("validation_mode", [False, True])
def test_auth_login_with_invalid_params(unauthenticated_api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check validation for login API

    The request payload contains the following 2 errors
    - username: invalid type
    - password: missing required parameter
    """
    helper.do_test_invalid_params(
        endpoint_func=unauthenticated_api_client.Auth.login,
        validation_mode=validation_mode,
        invalid_params=dict(username=123),
        num_expected_errors=2,
    )
