import pytest

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


def test_raw_options(unauthenticated_api_client: DemoAppAPIClient) -> None:
    """Test endpoint raw options"""
    # Call with the endpoint-level raw option
    endpoint_level_raw_options = unauthenticated_api_client._Test.redirect._raw_options
    assert endpoint_level_raw_options.get("follow_redirects") is True
    r = unauthenticated_api_client._Test.redirect()
    assert r.ok
    assert r.request.url == unauthenticated_api_client._Test.redirected.endpoint.url

    # Override the endpoint-level raw option
    r = unauthenticated_api_client._Test.redirect(raw_options={"follow_redirects": False})
    assert r.status_code == 301
    assert r.request.url == unauthenticated_api_client._Test.redirect.endpoint.url
    assert r._response.has_redirect_location
