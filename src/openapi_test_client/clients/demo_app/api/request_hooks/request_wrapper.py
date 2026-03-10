from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from openapi_test_client.libraries.core.types import APIResponse

P = ParamSpec("P")
R = TypeVar("R", bound=APIResponse)


def do_something_before_and_after_request(f: Callable[P, R]) -> Callable[P, R]:
    """This is a template of the request wrapper that will decorate an API request

    To enable this hook, add this function to the parent class's `request_wrapper` inside the base API class's
    pre_request_hook():
    >>> from typing import Callable
    >>> from openapi_test_client.clients.demo_app.api.request_hooks.request_wrapper import (
    >>>     do_something_before_and_after_request
    >>> )
    >>>
    >>> def request_wrapper(self) -> list[Callable]:
    >>>     request_wrappers = super().request_wrapper()    # noqa
    >>>     request_wrappers.append(do_something_before_and_after_request)
    >>>     return request_wrappers
    """

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Do something before request
        r = f(*args, **kwargs)
        # Do something after request
        return r

    return wrapper
