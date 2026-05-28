"""Unit tests for OpenAPI-specific endpoint behavior."""

from __future__ import annotations

import pytest

from openapi_test_client.libraries.openapi import Endpoint
from openapi_test_client.libraries.openapi.base import OpenAPIBase, OpenAPIClient

pytestmark = [pytest.mark.unittest]


class TestOpenAPIEndpointObject:
    """Tests for OpenAPI-specific Endpoint fields and behavior"""

    @pytest.mark.parametrize("with_instance", [True, False])
    def test_openapi_attrs(self, api_client: OpenAPIClient, api_class: type[OpenAPIBase], with_instance: bool) -> None:
        """Test that OpenAPIEndpoint has a tags field populated from the class TAGs"""

        if with_instance:
            ep = api_class(api_client).get_something.endpoint
        else:
            ep = api_class.get_something.endpoint
        assert isinstance(ep, Endpoint)
        assert ep.tags == ("Test",)
