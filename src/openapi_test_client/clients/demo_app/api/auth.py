from typing import Unpack

from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint
from openapi_test_client.libraries.api.types import Kwargs, Unset


class AuthAPI(DemoAppBaseAPI):
    TAGs = ("Auth",)

    @endpoint.is_public
    @endpoint.post("/v1/auth/login")
    def login(self, *, username: str = Unset, password: str = Unset, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Login"""
        ...

    @endpoint.is_public
    @endpoint.get("/v1/auth/logout")
    def logout(self, **kwargs: Unpack[Kwargs]) -> RestResponse:
        """Logout"""
        ...
