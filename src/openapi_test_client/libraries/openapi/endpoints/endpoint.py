"""OpenAPI-specific endpoint type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ParamSpec, cast

from openapi_test_client.libraries.core.endpoints.endpoint import Endpoint as _Endpoint

P = ParamSpec("P")

__all__ = ["Endpoint"]


@dataclass(frozen=True, slots=True, eq=False)
class Endpoint(_Endpoint[P]):
    """Endpoint subclass that carries OpenAPI-specific metadata.

    Extends the core Endpoint with the `tags` field populated from the API class's TAGs attribute.
    """

    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from openapi_test_client.libraries.openapi.base.api_class import OpenAPIBase

        object.__setattr__(self, "tags", cast(type[OpenAPIBase[Any]], self.api_class).TAGs)
