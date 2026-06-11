"""Unit tests for APIBase (api_class.py)."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from common_libs.clients.rest_client import RestResponse
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core import endpoint
from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.core.base.api_class import get_api_classes
from openapi_test_client.libraries.core.endpoints import Endpoint

pytestmark = [pytest.mark.unittest]


class TestAPIBaseInit:
    """Tests for APIBase.init()"""

    def test_init_raises_type_error_when_called_directly_on_api_base(self) -> None:
        """Test that calling init() directly on APIBase raises TypeError"""
        with pytest.raises(TypeError, match=re.escape("init() cannot be called directly from APIBase")):
            APIBase.init()

    def test_init_raises_runtime_error_when_not_called_from_init_py(self) -> None:
        """Test that calling init() from a non-__init__.py file raises RuntimeError"""

        class MyBaseAPI(APIBase):
            app_name = "test"

        # This test file is not __init__.py, so calling init() here raises
        with pytest.raises(RuntimeError, match=r"API classes must be initialized in __init__\.py"):
            MyBaseAPI.init()

    def test_init_populates_endpoints_on_discovered_classes(self, mocker: MockerFixture) -> None:
        """Test that init() populates the endpoints list on each discovered API class"""

        class DiscoveryBaseAPI(APIBase):
            app_name = "discovery-test"

        class DiscoveryConcreteAPI(DiscoveryBaseAPI):
            app_name = "discovery-test"

            @endpoint.get("/v1/items")
            def list_items(self) -> RestResponse: ...

            @endpoint.post("/v1/items")
            def create_item(self, name: str) -> RestResponse: ...

        mock_prev_frame = MagicMock()
        mock_prev_frame.f_globals = {"__name__": "fake_api_module"}
        mocker.patch("inspect.currentframe", return_value=MagicMock(f_back=mock_prev_frame))
        mocker.patch("inspect.getframeinfo", return_value=MagicMock(filename="/fake/api/__init__.py"))
        mocker.patch(
            f"{get_api_classes.__module__}.{get_api_classes.__name__}",
            return_value=[DiscoveryConcreteAPI],
        )

        result = DiscoveryBaseAPI.init()

        assert DiscoveryConcreteAPI in result
        assert DiscoveryConcreteAPI.endpoints is not None
        assert len(DiscoveryConcreteAPI.endpoints) == 2
        assert all(isinstance(ep, Endpoint) for ep in DiscoveryConcreteAPI.endpoints)

    def test_init_populates_base_class_endpoints_as_sorted_aggregate(self, mocker: MockerFixture) -> None:
        """Test that init() populates the base class endpoints list with sorted aggregate of all subclass endpoints"""

        class AggregateBaseAPI(APIBase):
            app_name = "agg-test"

        # AggregateAlphaAPI sorts before AggregateBetaAPI by class name
        class AggregateAlphaAPI(AggregateBaseAPI):
            app_name = "agg-test"

            @endpoint.get("/v1/alpha")
            def alpha(self) -> RestResponse: ...

        class AggregateBetaAPI(AggregateBaseAPI):
            app_name = "agg-test"

            @endpoint.get("/v1/beta")
            def beta(self) -> RestResponse: ...

        mock_prev_frame = MagicMock()
        mock_prev_frame.f_globals = {"__name__": "fake_agg_module"}
        mocker.patch("inspect.currentframe", return_value=MagicMock(f_back=mock_prev_frame))
        mocker.patch("inspect.getframeinfo", return_value=MagicMock(filename="/fake/api/__init__.py"))
        mocker.patch(
            f"{get_api_classes.__module__}.{get_api_classes.__name__}",
            return_value=[AggregateAlphaAPI, AggregateBetaAPI],
        )

        AggregateBaseAPI.init()

        assert AggregateBaseAPI.endpoints is not None
        # sorted by (api_class.__name__, method, path): AggregateAlphaAPI < AggregateBetaAPI
        paths = [ep.path for ep in AggregateBaseAPI.endpoints]
        assert paths == ["/v1/alpha", "/v1/beta"]

    def test_init_returns_discovered_api_classes(self, mocker: MockerFixture) -> None:
        """Test that init() returns the list of discovered API classes"""

        class ReturnBaseAPI(APIBase):
            app_name = "return-test"

        class ReturnAPI(ReturnBaseAPI):
            app_name = "return-test"

            @endpoint.get("/v1/things")
            def list_things(self) -> RestResponse: ...

        mock_prev_frame = MagicMock()
        mock_prev_frame.f_globals = {"__name__": "fake_return_module"}
        mocker.patch("inspect.currentframe", return_value=MagicMock(f_back=mock_prev_frame))
        mocker.patch("inspect.getframeinfo", return_value=MagicMock(filename="/fake/api/__init__.py"))
        mocker.patch(
            f"{get_api_classes.__module__}.{get_api_classes.__name__}",
            return_value=[ReturnAPI],
        )

        result = ReturnBaseAPI.init()

        assert result == [ReturnAPI]


class TestAPIBaseInstantiation:
    """Tests for APIBase.__init__"""

    def test_app_name_mismatch_raises_value_error(self, api_client: APIClient) -> None:
        """Test that instantiating an API class with a mismatched app_name raises ValueError"""

        class MismatchedAPI(APIBase):
            app_name = "wrong-app"

            @endpoint.get("/v1/test")
            def get_test(self) -> RestResponse: ...

        with pytest.raises(ValueError, match="app_name for API class"):
            MismatchedAPI(api_client)

    def test_instantiation_sets_env_and_rest_client(self, api_client: APIClient) -> None:
        """Test that APIBase.__init__ copies env and rest_client from the API client"""

        class MatchedAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/test")
            def get_test(self) -> RestResponse: ...

        instance = MatchedAPI(api_client)
        assert instance.api_client is api_client
        assert instance.rest_client is api_client.rest_client
        assert instance.env == api_client.env
