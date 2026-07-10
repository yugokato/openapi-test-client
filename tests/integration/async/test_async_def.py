import asyncio
from typing import Any, Unpack

import pytest
from httpx import HTTPError

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries import Endpoint, endpoint
from openapi_test_client.libraries.types import Kwargs, RestResponse

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


class _AsyncDefEndpointAPI(DemoAppBaseAPI):
    """Test-local API class with `async def` endpoint functions"""

    TAGs = ("Test",)

    @endpoint.get("/v1/test/echo/{value}")
    async def async_echo(self, value: int | str, /, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Echo the value, awaiting the rest client inline"""
        r = await self.rest_client.get(self.async_echo.endpoint.path.format(value=value))
        assert r.ok
        return r

    @endpoint.get("/v1/test/echo/{value}")
    async def async_echo_auto(self, value: int | str, /, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Echo the value, auto-generating the REST call"""
        ...


class _AsyncDefHookAPI(DemoAppBaseAPI):
    """Test-local API class with `async def` pre/post request hooks"""

    TAGs = ("Test",)

    def __init__(self, api_client: DemoAppAPIClient) -> None:
        super().__init__(api_client)
        self.call_stack: list[str] = []

    async def pre_request_hook(self, endpoint: Endpoint[Any], *path_params: Any, **params: Any) -> None:
        await asyncio.sleep(0)
        self.call_stack.append("pre")

    async def post_request_hook(
        self,
        endpoint: Endpoint[Any],
        response: RestResponse | None,
        exception: HTTPError | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        await asyncio.sleep(0)
        self.call_stack.append("post")

    @endpoint.get("/v1/test/echo/{value}")
    def echo(self, value: int | str, /, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Echo the value"""
        ...


async def test_async_def_endpoint_custom_body_awaits_inline(async_api_client: DemoAppAPIClient) -> None:
    """Test that an `async def` endpoint with a custom body can await the rest client inline and return its
    response"""
    instance = _AsyncDefEndpointAPI(async_api_client)
    r = await instance.async_echo("foo")
    assert isinstance(r, RestResponse)
    assert r.ok
    assert r.response == "foo"


async def test_async_def_endpoint_empty_body_auto_generates_call(async_api_client: DemoAppAPIClient) -> None:
    """Test that an `async def` endpoint with an empty body auto-generates the REST call"""
    instance = _AsyncDefEndpointAPI(async_api_client)
    r = await instance.async_echo_auto("bar")
    assert isinstance(r, RestResponse)
    assert r.ok
    assert r.response == "bar"


async def test_async_def_hooks_are_awaited(async_api_client: DemoAppAPIClient) -> None:
    """Test that `async def` pre_request_hook and post_request_hook are awaited around an async API call"""
    instance = _AsyncDefHookAPI(async_api_client)
    r = await instance.echo(0)
    assert r.ok
    assert instance.call_stack == ["pre", "post"]


def test_async_def_endpoint_on_sync_client_raises(unauthenticated_api_client: DemoAppAPIClient) -> None:
    """Test that calling an `async def` endpoint function on a sync client raises RuntimeError"""
    instance = _AsyncDefEndpointAPI(unauthenticated_api_client)
    with pytest.raises(RuntimeError, match=r"is defined with `async def`"):
        instance.async_echo(0)
