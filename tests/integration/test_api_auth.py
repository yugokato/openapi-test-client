import pytest

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from tests.integration import helper

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.parametrize("validation_mode", [False, True])
def test_user_login_logout(unauthenticated_api_client: DemoAppAPIClient, validation_mode: bool) -> None:
    """Check basic client/server functionality of Auth login/logout APIs"""
    r = unauthenticated_api_client.Auth.login(username="foo", password="bar", validate=validation_mode)
    assert r.ok
    assert set(r.response.keys()) == {"token"}
    assert unauthenticated_api_client.rest_client.get_bearer_token() == r.response["token"]

    r = unauthenticated_api_client.Auth.logout()
    assert r.ok
    assert r.response["message"] == "logged out"
    assert unauthenticated_api_client.rest_client.get_bearer_token() is None


@pytest.mark.parametrize("validation_mode", [False, True])
def test_user_login_with_invalid_params(unauthenticated_api_client: DemoAppAPIClient, validation_mode: bool) -> None:
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
