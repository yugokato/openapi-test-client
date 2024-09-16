from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app.api.base import DemoAppBaseAPI
from openapi_test_client.libraries.api.api_functions import endpoint


class AuthAPI(DemoAppBaseAPI):
    TAGs = ["Auth"]

    @endpoint.post("/v1/auth/login")
    def login(self, *, username: str = None, password: str = None, **kwargs) -> RestResponse:
        """Login"""
        ...

    @endpoint.get("/v1/auth/logout")
    def logout(self, **kwargs) -> RestResponse:
        """Logout"""
        ...