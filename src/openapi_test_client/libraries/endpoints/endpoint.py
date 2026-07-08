from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ParamSpec

from api_client_core.endpoints.endpoint import Endpoint as _Endpoint

if TYPE_CHECKING:
    from openapi_test_client.libraries.base.api_class import OpenAPIBase
    from openapi_test_client.libraries.types import EndpointModel

P = ParamSpec("P")

__all__ = ["Endpoint"]


@dataclass(frozen=True, slots=True, eq=False)
class Endpoint(_Endpoint[P]):
    """Endpoint subclass that carries OpenAPI-specific metadata.

    See the core's `Endpoint` class for details.
    """

    api_class: type[OpenAPIBase[Any]]
    model: type[EndpointModel]
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", self.api_class.TAGs)
