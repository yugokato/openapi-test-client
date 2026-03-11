from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import HTTPError

from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.types import APIResponse

from ..request_hooks.post_request import manage_auth_session

if TYPE_CHECKING:
    from openapi_test_client.libraries.core import Endpoint


class DemoAppBaseAPI(APIBase[Any]):
    """Base class for demo_app API classes"""

    app_name = "demo_app"
    endpoints: list[Endpoint] | None = None

    def post_request_hook(
        self,
        endpoint: Endpoint,
        response: APIResponse | None,
        exception: HTTPError | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        super().post_request_hook(endpoint, response, exception, *path_params, **params)
        if response and response.ok:
            if endpoint in self.api_client.Auth.endpoints:
                manage_auth_session(self.api_client, endpoint, response)
