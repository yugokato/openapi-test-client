import asyncio
import time
from contextlib import nullcontext

import pytest
from common_libs.clients.rest_client import RestResponse
from pytest import Subtests

from openapi_test_client import logger
from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.parametrize("quiet", [None, False, True])
async def test_async_client(async_api_client: DemoAppAPIClient, subtests: Subtests, quiet: bool) -> None:
    """Verify that the same API client works in async mode"""
    with subtests.test("API func calls"):
        r = await async_api_client.Auth.login(username="foo", password="bar", quiet=quiet)
        assert r.ok
        assert set(r.response.keys()) == {"token"}
        assert async_api_client.rest_client.get_bearer_token() == r.response["token"]

        r = await async_api_client.Users.get_users(quiet=quiet)
        assert r.ok
        assert len(r.response) > 0

        r = await async_api_client.Users.get_users(role="admin", quiet=quiet, validate=True)
        assert r.ok
        assert len(r.response) > 0

        r = await async_api_client.Auth.logout(quiet=quiet)
        assert r.ok
        assert r.response["message"] == "logged out"
        assert async_api_client.rest_client.get_bearer_token() is None

    with subtests.test("API func call (streaming)"):
        async with async_api_client._Test.echo.stream("foo", quiet=quiet) as r:
            assert r.ok
            assert not r._response.is_closed
            async for chunk in r.astream(chunk_size=1):
                assert isinstance(chunk, str)
            assert r._response.is_closed

    for i in range(2):
        with subtests.test(f"Concurrent API func calls {i + 1}"):
            delay = 0.5
            num_calls = 10
            start = time.perf_counter()
            if i == 0:
                tasks = [async_api_client._Test.wait(delay, quiet=quiet) for _ in range(num_calls)]
                results = await asyncio.gather(*tasks)
            else:
                results = await async_api_client._Test.wait.with_concurrency(delay, num=num_calls, quiet=quiet)
            time_elapsed = time.perf_counter() - start
            assert delay < time_elapsed < delay * (num_calls / 2)
            assert all(x.ok for x in results)

    for some_id, is_valid in [(0, True), (1, False)]:
        with subtests.test("Custom API func logic", is_valid_logic=is_valid):
            with (
                nullcontext()
                if is_valid
                else pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object")
            ):
                r = await async_api_client._Test.echo(some_id, quiet=quiet)

            if is_valid:
                assert isinstance(r, RestResponse)
                assert r.ok
                assert r.response == some_id * 2

    with subtests.test("With retry"):
        r = await async_api_client._Test.echo.with_retry(0, condition=lambda r: r.ok, retry_after=0.5, quiet=quiet)
        assert r.ok
        assert r.request.retried is not None

    with subtests.test("With lock"):
        r = await async_api_client._Test.echo.with_lock(0, quiet=quiet)
        assert r.ok


@pytest.mark.parametrize("quiet", [None, False, True])
async def test_async_client_request_failures(
    async_api_client: DemoAppAPIClient, subtests: Subtests, quiet: bool
) -> None:
    """Verify async mode handles failed requests correctly, including request/response hooks"""
    with subtests.test("API func call failure"):
        r = await async_api_client.Auth.login(quiet=quiet)
        assert not r.ok

    with subtests.test("API func call failure with validation mode"):
        with pytest.raises(ValueError, match="Request parameter validation failed") as e:
            _ = await async_api_client.Auth.login(validate=True, quiet=quiet)
        logger.info(e.value)

    with subtests.test("API func call failure (streaming)"):
        async with async_api_client._Test.wait.stream("foo", quiet=quiet) as r:
            assert not r.ok
            assert r._response.is_closed
            async for chunk in r.astream(chunk_size=1):
                assert isinstance(chunk, str)

    for i in range(2):
        with subtests.test(f"Concurrent API func call failures {i + 1}"):
            invalid_delay = "foo"
            num_calls = 3
            if i == 0:
                tasks = [async_api_client._Test.wait(invalid_delay, quiet=quiet) for _ in range(num_calls)]
                results = await asyncio.gather(*tasks)
            else:
                results = await async_api_client._Test.wait.with_concurrency(invalid_delay, num=num_calls, quiet=quiet)
            assert all(not r.ok for r in results)

    with subtests.test("API func call failure with retry"):
        r = await async_api_client._Test.wait.with_retry("foo", condition=lambda r: True, retry_after=0.5, quiet=quiet)
        assert not r.ok
        assert r.request.retried is not None

    with subtests.test("API func call failure with lock"):
        r = await async_api_client._Test.wait.with_lock("foo", quiet=quiet)
        assert not r.ok
