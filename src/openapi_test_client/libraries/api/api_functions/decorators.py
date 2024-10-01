from collections.abc import Callable
from functools import wraps
from typing import ParamSpec

from common_libs.clients.rest_client import RestResponse
from common_libs.logging import get_logger

from openapi_test_client.libraries.api import endpoint

P = ParamSpec("P")


logger = get_logger(__name__)


@endpoint.decorator
def my_endpoint_decorator(f: Callable[P, RestResponse]) -> Callable[P, RestResponse]:
    """Just an example of an endpoint decorator

    NOTE:
        - All endpoint decorators must be decorated with `@endpoint.decorator`
        - The decorator must be added above the `@endpoint.<method>(<path>)` decorator

    Usage:
        >>> @my_endpoint_decorator
        >>> @endpoint.get("/v1/something")
        >>> def get_something(self) -> RestResponse:
        >>>     ...
    """

    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> RestResponse:
        return f(*args, **kwargs)

    return wrapper


@endpoint.decorator
def apply_default(**params_with_default_value):
    """Automatically apply default value for the given API function parameters if they are not explicitly given to an
    API call

    Since our API function will always be generated with default value None for each parameter, you can use this
    decorator to control the actual default value, if you need to

    Usage:
        >>> @apply_default(param_a=123, param_b="test")
        >>> @endpoint.get("/v1/something")
        >>> def get_something(self, *, param_a: int = None, param_b: str = None, **kwargs) -> RestResponse:
        >>>     ...
    """

    def decorator_with_args(f: Callable[P, RestResponse]) -> Callable[P, RestResponse]:
        @wraps(f)
        def wrapper(*_: P.args, **params: P.kwargs) -> RestResponse:
            for param_name, default_value in params_with_default_value.items():
                if param_name not in params:
                    params[param_name] = default_value

            return f(*_, **params)

        return wrapper

    return decorator_with_args
