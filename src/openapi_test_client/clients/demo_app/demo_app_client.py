from functools import cached_property

from openapi_test_client.clients.demo_app.api._test import _TestAPI
from openapi_test_client.clients.openapi import OpenAPIClient

from .api.auth import AuthAPI
from .api.users import UsersAPI


class DemoAppAPIClient(OpenAPIClient):
    """API client for demo_app

    Usage:
    >>> client = DemoAppAPIClient()
    >>> r = client.Auth.login(username="foo", password="bar")
    >>> assert r.status_code == 200
    >>> token = r.response["token"]
    """

    def __init__(self, env: str = "dev", base_url: str | None = None, async_mode: bool = False) -> None:
        super().__init__("demo_app", env=env, base_url=base_url, doc="openapi.json", async_mode=async_mode)

    @cached_property
    def Auth(self) -> AuthAPI:
        return AuthAPI(self)

    @cached_property
    def Users(self) -> UsersAPI:
        return UsersAPI(self)

    @cached_property
    def _Test(self) -> _TestAPI:
        return _TestAPI(self)
