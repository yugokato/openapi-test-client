from typing import ParamSpec

from api_client_core.endpoints.endpoint_handler import EndpointHandler as _EndpointHandler

__all__ = ["EndpointHandler"]

P = ParamSpec("P")


class EndpointHandler(_EndpointHandler[P]):
    """Thin typing overlay around the core `EndpointHandler`.

    See the `endpoint_handler.pyi` stub for the narrowed `__get__` return type. See the core `EndpointHandler` class
    for behavior.
    """
