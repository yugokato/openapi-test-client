from __future__ import annotations

import inspect
from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from common_libs.logging import get_logger
from httpx import HTTPError

from openapi_test_client.libraries.core.types import APIResponse

if TYPE_CHECKING:
    from openapi_test_client.clients.openapi import OpenAPIClient
    from openapi_test_client.libraries.core import Endpoint

T = TypeVar("T", bound="OpenAPIClient")

logger = get_logger(__name__)


class APIBase(Generic[T], metaclass=ABCMeta):
    """Base API class"""

    app_name: str | None = None
    is_documented: bool = True
    is_deprecated: bool = False
    endpoints: list[Endpoint] | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the endpoint decorator stack when an API class is defined."""
        super().__init_subclass__(**kwargs)
        from openapi_test_client.libraries.core.endpoints.endpoint_handler import EndpointHandler, PendingHandler

        def wraps_handler(func: Any, _depth: int = 10) -> bool:
            if _depth == 0:
                return False
            if isinstance(inspect.unwrap(func), (EndpointHandler, PendingHandler)):
                return True
            if func.__closure__:
                for cell in func.__closure__:
                    try:
                        cell_content = cell.cell_contents
                        if isinstance(cell_content, (EndpointHandler, PendingHandler)):
                            return True
                        if inspect.isfunction(cell_content) and wraps_handler(cell_content, _depth - 1):
                            return True
                    except ValueError:
                        pass
            return False

        for attr_name, attr in cls.__dict__.items():
            func = attr.func if isinstance(attr, PendingHandler) else attr
            if inspect.isfunction(func) and wraps_handler(func):
                raise RuntimeError(
                    f"{cls.__name__}.{attr_name}: Detected an unregistered decorator on this API function. "
                    f"Decorators must be registered by applying @endpoint.decorator on the decorator definition."
                )
            elif isinstance(attr, PendingHandler):
                raise RuntimeError(
                    f"{cls.__name__}.{attr_name}: Invalid API function definition. Requires @endpoint.<method>() "
                    f"decorator."
                )

    def __init__(self, api_client: T):
        if self.app_name != api_client.app_name:
            raise ValueError(
                f"app_name for API class ({self.app_name}) and API client ({api_client.app_name}) must match"
            )
        self.env = api_client.env
        self.api_client = api_client
        self.rest_client = api_client.rest_client

    @property
    @abstractmethod
    def TAGs(self) -> tuple[str, ...]:
        """API Tags defined in the swagger doc. Every API class MUST have this attribute"""
        raise NotImplementedError

    def pre_request_hook(self, endpoint: Endpoint, *path_params: Any, **params: Any) -> None:
        """Hook function called before each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param path_params: API path parameters
        :param params: API parameters sent with the request
        """
        ...

    def post_request_hook(
        self,
        endpoint: Endpoint,
        response: APIResponse | None,
        exception: HTTPError | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        """Hook function called after each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param response: Response of the API request
        :param exception: An exception raised in the httpx client
        :param path_params: API path parameters for the request
        :param params: API parameters sent with the request
        """
        ...

    def request_wrapper(self) -> list[Callable[..., Any]]:
        """Decorator(s) to wrap each request call

        NOTE:
            - If multiple wrappers are returned, they will be applied from the last one, which means the first one will
              be processed first.
            - The first argument of the wrapper function inside the decorator is an instance of EndpointFunc class
        """
        return []
