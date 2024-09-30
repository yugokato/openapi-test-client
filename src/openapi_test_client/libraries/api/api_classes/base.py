from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Callable, Optional

from common_libs.clients.rest_client import RestResponse
from common_libs.logging import get_logger
from requests.exceptions import RequestException

if TYPE_CHECKING:
    from openapi_test_client.clients import APIClientType
    from openapi_test_client.libraries.api import Endpoint


logger = get_logger(__name__)


class APIBase(metaclass=ABCMeta):
    """Base API class"""

    app_name: Optional[str] = None
    is_documented: bool = True
    is_deprecated: bool = False
    endpoints: Optional[list[Endpoint]] = None

    def __init__(self, api_client: APIClientType):
        if self.app_name != api_client.app_name:
            raise ValueError(
                f"app_name for API class ({self.app_name}) and API client ({api_client.app_name}) must match"
            )
        self.env = api_client.env
        self.api_client = api_client
        self.rest_client = api_client.rest_client

    @property
    @classmethod
    @abstractmethod
    def TAGs(cls) -> tuple[str, ...]:
        """API Tags defined in the swagger doc. Every API class MUST have this attribute"""
        raise NotImplementedError

    def pre_request_hook(self, endpoint: Endpoint, *path_params, **params):
        """Hook function called before each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param path_params: API path parameters
        :param params: API parameters sent with the request
        """
        ...

    def post_request_hook(
        self,
        endpoint: Endpoint,
        response: Optional[RestResponse],
        request_exception: Optional[RequestException],
        *path_params,
        **params,
    ):
        """Hook function called after each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param response: Response of the API request
        :param request_exception: An exception raised in requests library
        :param path_params: API path parameters for the request
        :param params: API parameters sent with the request
        """
        ...

    def request_wrapper(self) -> list[Callable]:
        """Decorator(s) to wrap each request call

        NOTE:
            - If multiple wrappers are returned, they will be applied from the last one, which means the first one will
              be processed first.
            - The first argument of the wrapper function inside the decorator is an instance of EndpointFunc class
        """
        return []
