from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from common_libs.clients.rest_client import RestResponse
from common_libs.logging import get_logger
from requests.exceptions import RequestException

if TYPE_CHECKING:
    from openapi_test_client.clients import OpenAPIClient
    from openapi_test_client.libraries.api import Endpoint

T = TypeVar("T", bound="OpenAPIClient")

logger = get_logger(__name__)


class APIBase(Generic[T], metaclass=ABCMeta):
    """Base API class"""

    app_name: str | None = None
    is_documented: bool = True
    is_deprecated: bool = False
    endpoints: list[Endpoint] | None = None

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
        response: RestResponse | None,
        request_exception: RequestException | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        """Hook function called after each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param response: Response of the API request
        :param request_exception: An exception raised in requests library
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
