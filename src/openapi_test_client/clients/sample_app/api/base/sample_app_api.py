from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from common_libs.clients.rest_client import RestResponse
from requests.exceptions import RequestException

from openapi_test_client.libraries.api.api_classes.base import APIBase

from ..request_hooks.post_request import manage_auth_session

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import Endpoint


class SampleAppBaseAPI(APIBase):
    """Base class for sample_app API classes"""

    app_name = "sample_app"
    endpoints: Optional[list[Endpoint]] = None

    def post_request_hook(
        self,
        endpoint: Endpoint,
        response: Optional[RestResponse],
        request_exception: Optional[RequestException],
        *path_params,
        **params,
    ):
        super().post_request_hook(endpoint, response, request_exception, *path_params, **params)
        if response and response.ok:
            if endpoint in self.api_client.AUTH.endpoints:
                manage_auth_session(self.api_client, endpoint, response)
