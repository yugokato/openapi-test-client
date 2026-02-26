from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from common_libs.clients.rest_client import RestResponse
from common_libs.logging import get_logger

from openapi_test_client.libraries.core import endpoint

P = ParamSpec("P")
R = TypeVar("R", bound=RestResponse)


logger = get_logger(__name__)


@endpoint.decorator
def my_endpoint_decorator(f: Callable[P, R]) -> Callable[P, R]:
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
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return f(*args, **kwargs)

    return wrapper


@endpoint.decorator
def apply_default(**params_with_default_value: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Automatically apply default value for the given API function parameters if they are not explicitly given to an
    API call

    Since our API function will always be generated with default value None for each parameter, you can use this
    decorator to control the actual default value, if you need to

    Usage:
        >>> @apply_default(param_a=123, param_b="test")
        >>> @endpoint.get("/v1/something")
        >>> def get_something(self, *, param_a: int = Unset, param_b: str = Unset, **kwargs) -> RestResponse:
        >>>     ...
    """

    def decorator_with_args(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*_: P.args, **params: P.kwargs) -> RestResponse:
            for param_name, default_value in params_with_default_value.items():
                if param_name not in params:
                    params[param_name] = default_value

            return f(*_, **params)

        return wrapper

    return decorator_with_args
