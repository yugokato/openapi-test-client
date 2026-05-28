from collections.abc import Callable
from typing import TypeVar

import pytest
from pytest import FixtureRequest

from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.openapi.base import OpenAPIBase, OpenAPIClient

ClientT = TypeVar("ClientT", bound=APIClient | OpenAPIClient)
ClassT = TypeVar("ClassT", bound=APIBase | OpenAPIBase)


@pytest.fixture(scope="module")
def api_client_factory() -> None:
    """A general API client factory that must be overridden in each test directory"""
    raise NotImplementedError("api_client_factory fixture must be implemented")


@pytest.fixture(scope="module")
def api_class_factory() -> None:
    """A general API class factory that must be overridden in each test directory"""
    raise NotImplementedError("api_class_factory fixture must be implemented")


@pytest.fixture
def api_client(request: FixtureRequest, api_client_factory: Callable[..., ClientT]) -> ClientT:
    """A general API client for testing, with support for async mode via test parameterization"""
    if hasattr(request, "param"):
        mode = request.param
        assert mode in ["sync", "async"], "Invalid mode parameter, must be 'sync' or 'async'"
        is_async = mode == "async"
        return api_client_factory(async_mode=is_async)
    return api_client_factory()


@pytest.fixture(scope="module")
def api_client_async(api_client_factory: Callable[..., ClientT]) -> ClientT:
    """A general API client for testing (async)"""
    return api_client_factory(async_mode=True)


@pytest.fixture
def api_class(api_client: APIClient, api_class_factory: Callable[[ClientT], type[ClassT]]) -> type[ClassT]:
    """A testable API class with one endpoint function"""

    return api_class_factory(api_client)


@pytest.fixture(scope="module")
def api_class_async(api_client_async: APIClient, api_class_factory: Callable[[ClientT], type[ClassT]]) -> type[ClassT]:
    """A testable API class with one endpoint function (async)"""

    return api_class_factory(api_client_async)
