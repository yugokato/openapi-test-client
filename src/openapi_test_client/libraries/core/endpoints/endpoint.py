from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from common_libs.clients.rest_client import APIResponse

from openapi_test_client.libraries.core.types import EndpointModel

if TYPE_CHECKING:
    from openapi_test_client.clients.openapi import OpenAPIClient
    from openapi_test_client.libraries.core.api_classes import APIBase
    from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointFunc


__all__ = ["Endpoint"]


@dataclass(frozen=True, slots=True)
class Endpoint:
    """An Endpoint class to hold various endpoint data associated to an API class function

    This is accessible via an EndpointFunc object (see docstrings of the `endpoint` class below).
    """

    tags: tuple[str, ...]
    api_class: type[APIBase]
    method: str
    path: str
    func_name: str
    model: type[EndpointModel]
    url: str | None = None  # Available only for an endpoint object accessed via an API client instance
    content_type: str | None = None
    is_public: bool = False
    is_documented: bool = True
    is_deprecated: bool = False

    def __str__(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, Endpoint) and str(self) == str(obj)

    def __hash__(self) -> int:
        return hash(str(self))

    def __call__(
        self,
        api_client: OpenAPIClient,
        *path_params: Any,
        quiet: bool = False,
        validate: bool = False,
        with_hooks: bool = True,
        raw_options: dict[str, Any] | None = None,
        **body_or_query_params: Any,
    ) -> APIResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint using the given API client

        :param path_params: Path parameters
        :param quiet: A flag to suppress API request/response log
        :param validate: Validate the request parameter in Pydantic strict mode
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param body_or_query_params: Request body or query parameters

        Example:
            >>> from openapi_test_client.clients.demo_app import DemoAppAPIClient
            >>>
            >>> client = DemoAppAPIClient()
            >>> r = client.Auth.login(username="foo", password="bar")
            >>> # Above API call can be also done directly from the endpoint object, if you need to:
            >>> endpoint = client.Auth.login.endpoint
            >>> r2 = endpoint(client, username="foo", password="bar")
        """
        api_class = self.api_class(api_client)
        endpoint_func: EndpointFunc = getattr(api_class, self.func_name)
        func_call = partial(
            endpoint_func,
            *path_params,
            quiet=quiet,
            with_hooks=with_hooks,
            validate=validate,
            raw_options=raw_options,
            **body_or_query_params,
        )
        if api_client.async_mode:
            return asyncio.run(func_call())
        else:
            return func_call()
