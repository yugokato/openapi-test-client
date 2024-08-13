from functools import wraps
from typing import TYPE_CHECKING, Callable, ParamSpec

from common_libs.clients.rest_client import RestResponse

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import EndpointFunc


P = ParamSpec("P")


def do_something_before_and_after_request(f: Callable[P, RestResponse]) -> Callable[P, RestResponse]:
    """This is a template of the request wrapper that will decorate an API request"

    To enable this hook, add this function to the parent class's `request_wrapper` inside the base API class's pre_request_hook():
    >>> from typing import Callable
    >>> from openapi_test_client.clients.sample_app.api.request_hooks.request_wrapper import do_something_before_and_after_request
    >>>
    >>> def request_wrapper(self) -> list[Callable]:
    >>>     request_wrappers = super().request_wrapper()    # noqa
    >>>     request_wrappers.append(do_something_before_and_after_request)
    >>>     return request_wrappers
    """

    @wraps(f)
    def wrapper(endpoint_func: "EndpointFunc", *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        # Do something before request
        r = f(endpoint_func, *args, **kwargs)
        # Do something after request
        return r

    return wrapper
