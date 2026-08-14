from functools import cached_property
from typing import Any

from openapi_test_client.libraries.base.api_client import OpenAPIClient

from .api._test import _TestAPI
from .api.auth import AuthAPI
from .api.users import UsersAPI


class DemoAppAPIClient(OpenAPIClient):
    """API client for demo_app

    Usage:
    >>> client = DemoAppAPIClient()
    >>> r = client.auth.login(username="foo", password="bar")
    >>> assert r.status_code == 200
    >>> token = r.response["token"]
    """

    app_name = "demo_app"

    def __init__(
        self,
        *,
        env: str = "dev",
        base_url: str | None = None,
        async_mode: bool = False,
        raise_on_error: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            env=env,
            base_url=base_url,
            doc="openapi.json",
            async_mode=async_mode,
            raise_on_error=raise_on_error,
            **kwargs,
        )

    @cached_property
    def auth(self) -> AuthAPI:
        return AuthAPI(self)

    @cached_property
    def users(self) -> UsersAPI:
        return UsersAPI(self)

    @cached_property
    def _test(self) -> _TestAPI:
        return _TestAPI(self)
