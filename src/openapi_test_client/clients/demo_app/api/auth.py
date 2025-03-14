from typing import Any

from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Unset


class AuthAPI(DemoAppBaseAPI):
    TAGs = ("Auth",)

    @endpoint.is_public
    @endpoint.post("/v1/auth/login")
    def login(self, *, username: str = Unset, password: str = Unset, **kwargs: Any) -> RestResponse:
        """Login"""
        ...

    @endpoint.is_public
    @endpoint.get("/v1/auth/logout")
    def logout(self, **kwargs: Any) -> RestResponse:
        """Logout"""
        ...
