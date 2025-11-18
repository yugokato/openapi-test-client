from typing import Any, Unpack

from common_libs.clients.rest_client import APIResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Kwargs


class _TestAPI(DemoAppBaseAPI):
    TAGs = ("Test",)

    @endpoint.get("/v1/test/echo/{number}")
    def echo(self, number: int, /, **kwargs: Unpack[Kwargs]) -> Any:
        """Test endpoint that just echos the specified number"""
        # Defines custom API func logic for testing
        if number % 2 == 0:
            # Valid logic: Call the endpoint with multiplied number. This returns a RestResponse object
            return self.rest_client.get(self.echo.endpoint.path.format(number=number * 2))
        else:
            # Invalid. RestResponse object is not returned
            return number

    @endpoint.get("/v1/test/wait/{delay}")
    def wait(self, delay: float | int, /, **kwargs: Unpack[Kwargs]) -> APIResponse:
        """Test endpoint that returns a response after waiting for the specified delay"""
        ...

    @endpoint.get("/v1/test/redirect", follow_redirects=True)
    def redirect(self, **kwargs: Unpack[Kwargs]) -> APIResponse:
        """Test endpoint that redirects to /redirected"""
        ...

    @endpoint.get("/v1/test/redirected")
    def redirected(self, **kwargs: Unpack[Kwargs]) -> APIResponse:
        """Test endpoint for the redirected route"""
        ...
