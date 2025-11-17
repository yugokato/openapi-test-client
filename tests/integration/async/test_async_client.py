import pytest

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.asyncio
async def test_async_client(async_api_client: DemoAppAPIClient) -> None:
    """Verify that an API client works in async mode"""
    r = await async_api_client.Auth.login(username="foo", password="bar")
    assert r.ok
    assert set(r.response.keys()) == {"token"}
    assert async_api_client.rest_client.get_bearer_token() == r.response["token"]

    r = await async_api_client.Users.get_users()
    assert r.ok
    assert len(r.response) > 0

    # stream
    async with async_api_client.Users.get_users.stream() as r:
        assert r.ok
        assert not r._response.is_closed
        async for chunk in r.astream():
            assert isinstance(chunk, str)
        assert r._response.is_closed

    r = await async_api_client.Auth.logout()
    assert r.ok
    assert r.response["message"] == "logged out"
    assert async_api_client.rest_client.get_bearer_token() is None
