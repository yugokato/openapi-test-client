from typing import Any, Unpack

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Kwargs


class _TestAPI(DemoAppBaseAPI):
    TAGs = ("_Test",)

    @endpoint.get("/v1/test/{some_id}")
    def test(self, some_id: int, **kwargs: Unpack[Kwargs]) -> Any:
        """Test endpoint that just echos the specified ID value"""

        # Defines custom API func logic for testing
        if some_id % 2 == 0:
            # Valid logic: Call the endpoint with multiplied ID. This retuns a RestResponse object
            return self.rest_client.get(self.test.endpoint.path.format(some_id=some_id * 2))
        else:
            # Invalid. RestResponse object is not returned
            return some_id
