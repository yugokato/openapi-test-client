from functools import cached_property

from openapi_test_client.clients.base import OpenAPIClient

from .api.auth import AuthAPI
from .api.users import UsersAPI


class SampleAppAPIClient(OpenAPIClient):
    """API client for sample_app

    Usage:
    >>> client = SampleAppAPIClient()
    >>> r = client.AUTH.login(username="foo", password="bar")
    >>> assert r.status_code == 200
    >>> token = r.response["token"]
    """

    def __init__(self, env: str = "dev"):
        super().__init__("sample_app", env=env, doc="openapi.json")

    @cached_property
    def AUTH(self):
        return AuthAPI(self)

    @cached_property
    def USERS(self):
        return UsersAPI(self)
