from typing import Unpack

from common_libs.clients.rest_client import APIResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.core.endpoints import endpoint
from openapi_test_client.libraries.core.types import Kwargs, Unset


class AuthAPI(DemoAppBaseAPI):
    TAGs = ("Auth",)

    @endpoint.is_public
    @endpoint.post("/v1/auth/login")
    def login(self, *, username: str = Unset, password: str = Unset, **kwargs: Unpack[Kwargs]) -> APIResponse:
        """Login"""
        ...

    @endpoint.is_public
    @endpoint.post("/v1/auth/logout")
    def logout(self, **kwargs: Unpack[Kwargs]) -> APIResponse:
        """Logout"""
        ...
