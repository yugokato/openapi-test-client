from typing import Any, ParamSpec

from api_client_core.endpoints.endpoint_handler import EndpointHandler as _EndpointHandler

from openapi_test_client.libraries.base import OpenAPIBase
from openapi_test_client.libraries.endpoints.endpoint_func import AsyncEndpointFunc, SyncEndpointFunc

__all__ = ["EndpointHandler"]

P = ParamSpec("P")

class EndpointHandler(_EndpointHandler[P]):
    """Narrowed-type stub for `EndpointHandler`.

    See the api-client-core `EndpointHandler` class for behavior.
    """

    def __get__(
        self, instance: OpenAPIBase[Any] | None, owner: type[OpenAPIBase[Any]]
    ) -> SyncEndpointFunc[P] | AsyncEndpointFunc[P]: ...
