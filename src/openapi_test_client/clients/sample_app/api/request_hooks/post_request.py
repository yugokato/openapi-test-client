from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common_libs.clients.rest_client import RestResponse

    from openapi_test_client.clients.sample_app import SampleAppAPIClient
    from openapi_test_client.libraries.api import Endpoint


def do_something_after_request(
    api_client: SampleAppAPIClient, endpoint: Endpoint, r: RestResponse, *path_params, **params
):
    """This is a template of the post-request hook that will be called right after making a request

    To enable this hook, call this function inside the base API class's post_request_hook():
    >>> from typing import Optional
    >>> from requests.exceptions import RequestException
    >>> from openapi_test_client.clients.sample_app.api.request_hooks.post_request import do_something_after_request
    >>>
    >>> def post_request_hook(
    >>>     self,
    >>>     endpoint: Endpoint,
    >>>     response: Optional[RestResponse],
    >>>     request_exception: Optional[RequestException],
    >>>     *path_params,
    >>>     **params,
    >>> ):
    >>>     super().post_request_hook(endpoint, response, request_exception, *path_params, **params)    # type: ignore
    >>>     do_something_after_request(self.api_client, endpoint, response, *path_params, *params)
    """
    # Do something after request
    pass


def manage_auth_session(api_client: SampleAppAPIClient, endpoint: Endpoint, r: RestResponse):
    """Manage auth after successful login/logout

    :param api_client: API client
    :param endpoint: The Endpoint object of the API endpoint
    :param r: RestResponse object returned from the request
    """
    if endpoint == api_client.AUTH.login.endpoint:
        token = r.response["token"]
        api_client.rest_client.set_bearer_token(token)
    elif endpoint == api_client.AUTH.logout.endpoint:
        api_client.rest_client.unset_bear_token()
