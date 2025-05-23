from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openapi_test_client.clients.demo_app import DemoAppAPIClient
    from openapi_test_client.libraries.api import Endpoint


def do_something_before_request(api_client: DemoAppAPIClient, endpoint: Endpoint, **params: Any) -> None:
    """This is a template of the pre-request hook that will be called right before making a request

    To enable this hook, call this function inside the base API class's pre_request_hook():
    >>> from openapi_test_client.clients.demo_app.api.request_hooks.pre_request import do_something_before_request
    >>>
    >>> def pre_request_hook(self, endpoint: Endpoint, *path_params, **params):
    >>>     do_something_before_request(self.api_client, endpoint, *params)
    """
    # Do something before request
    ...
