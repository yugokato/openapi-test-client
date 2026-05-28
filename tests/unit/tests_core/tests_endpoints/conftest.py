from collections.abc import Callable

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.libraries.core import endpoint
from openapi_test_client.libraries.core.base import APIBase, APIClient


@pytest.fixture(scope="module")
def api_class_factory() -> Callable[..., type[APIBase]]:
    """API class factory that creates a testable API class with one endpoint function"""

    def create_api_class(api_client: APIClient) -> type[APIBase]:
        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/something")
            def get_something(self) -> RestResponse: ...

        return TestAPI

    return create_api_class
