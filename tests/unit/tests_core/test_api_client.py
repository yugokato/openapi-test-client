"""Unit tests for APIClient (api_client.py)."""

from __future__ import annotations

import asyncio

import pytest
from common_libs.clients.rest_client import AsyncRestClient, RestClient
from httpx import AsyncClient, Client
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core.base.api_client import APIClient

pytestmark = [pytest.mark.unittest]


BASE_URL = "https://api.example.com"


class TestAPIClientInit:
    """Tests for APIClient.__init__"""

    def test_init_with_base_url_creates_sync_rest_client(self) -> None:
        """Test that providing base_url without rest_client creates a RestClient in sync mode"""
        client = APIClient("myapp", base_url=BASE_URL)
        assert isinstance(client.rest_client, RestClient)
        assert client.base_url == BASE_URL
        assert client.app_name == "myapp"
        assert client.async_mode is False

    async def test_init_with_base_url_creates_async_rest_client_in_async_mode(self) -> None:
        """Test that async_mode=True with base_url creates an AsyncRestClient"""
        client = APIClient("myapp", base_url=BASE_URL, async_mode=True)
        assert isinstance(client.rest_client, AsyncRestClient)
        assert client.async_mode is True

    def test_init_raises_when_neither_base_url_nor_rest_client_provided(self) -> None:
        """Test that omitting both base_url and rest_client raises ValueError"""
        with pytest.raises(ValueError, match="base_url is required when rest_client is not provided"):
            APIClient("myapp")

    def test_init_raises_when_both_base_url_and_rest_client_provided(self) -> None:
        """Test that providing both base_url and rest_client raises ValueError"""
        rest_client = RestClient(BASE_URL)
        with pytest.raises(ValueError, match="base_url is not supported when rest_client is provided"):
            APIClient("myapp", base_url=BASE_URL, rest_client=rest_client)

    def test_init_raises_when_sync_rest_client_given_in_async_mode(self) -> None:
        """Test that passing a sync RestClient with async_mode=True raises TypeError"""
        rest_client = RestClient(BASE_URL)
        with pytest.raises(TypeError, match=f"rest_client must be of type {AsyncRestClient.__name__}"):
            APIClient("myapp", rest_client=rest_client, async_mode=True)

    def test_init_raises_when_async_rest_client_given_in_sync_mode(self) -> None:
        """Test that passing an AsyncRestClient with async_mode=False raises TypeError"""

        rest_client = AsyncRestClient(BASE_URL)
        try:
            with pytest.raises(TypeError, match=f"rest_client must be of type {RestClient.__name__}"):
                APIClient("myapp", rest_client=rest_client, async_mode=False)
        finally:
            asyncio.run(rest_client.close())

    def test_init_raises_when_created_inside_running_event_loop(self) -> None:
        """Test that creating a sync APIClient inside a running event loop raises RuntimeError"""

        async def create_sync_client() -> None:
            APIClient("myapp", base_url=BASE_URL)

        with pytest.raises(RuntimeError, match="cannot be used in sync mode inside async context"):
            asyncio.run(create_sync_client())

    def test_init_with_rest_client_sets_base_url_from_rest_client(self) -> None:
        """Test that providing rest_client copies its base_url"""
        rest_client = RestClient(BASE_URL)
        client = APIClient("myapp", rest_client=rest_client)
        assert client.base_url == BASE_URL
        assert client.rest_client is rest_client

    def test_env_defaults_to_none(self) -> None:
        """Test that env defaults to None when not provided"""
        client = APIClient("myapp", base_url=BASE_URL)
        assert client.env is None

    def test_env_stored_when_provided(self) -> None:
        """Test that env is stored when explicitly provided"""
        client = APIClient("myapp", base_url=BASE_URL, env="dev")
        assert client.env == "dev"


class TestAPIClientContextManager:
    """Tests for APIClient sync and async context manager support"""

    def test_sync_context_manager_closes_rest_client(self, mocker: MockerFixture) -> None:
        """Test that the sync context manager calls rest_client.close() on exit"""
        mock_close = mocker.patch.object(Client, "close")
        with APIClient("myapp", base_url=BASE_URL) as client:
            assert isinstance(client, APIClient)
        mock_close.assert_called_once()

    async def test_async_context_manager_closes_rest_client(self, mocker: MockerFixture) -> None:
        """Test that the async context manager calls rest_client.close() on exit"""
        mocker.patch.object(AsyncClient, "aclose")
        rest_client = AsyncRestClient(BASE_URL)
        mocker.patch.object(rest_client, "close", return_value=None)

        async with APIClient("myapp", rest_client=rest_client, async_mode=True) as client:
            assert isinstance(client, APIClient)

        rest_client.close.assert_called_once()

    def test_sync_context_manager_raises_in_async_mode(self) -> None:
        """Test that using `with` on an async-mode client raises TypeError instead of leaking the connection"""
        client = APIClient("myapp", base_url=BASE_URL, async_mode=True)
        with pytest.raises(TypeError, match="async mode"), client:
            ...

    def test_async_context_manager_raises_in_sync_mode(self) -> None:
        """Test that using `async with` on a sync-mode client raises a clear TypeError"""
        client = APIClient("myapp", base_url=BASE_URL)

        async def _enter() -> None:
            async with client:
                ...

        with pytest.raises(TypeError, match="sync mode"):
            asyncio.run(_enter())


class TestAPIClientBaseUrl:
    """Tests for the APIClient.base_url property setter"""

    def test_base_url_setter_updates_internal_url(self) -> None:
        """Test that setting base_url updates the _base_url attribute"""
        client = APIClient("myapp", base_url=BASE_URL)
        new_url = "https://staging.api.example.com"
        client.base_url = new_url
        assert client.base_url == new_url

    def test_base_url_setter_propagates_to_rest_client(self) -> None:
        """Test that setting base_url propagates to the underlying rest_client"""
        client = APIClient("myapp", base_url=BASE_URL)
        new_url = "https://staging.api.example.com"
        client.base_url = new_url
        assert client.rest_client.base_url == new_url
