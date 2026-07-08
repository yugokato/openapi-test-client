from __future__ import annotations

from typing import ParamSpec, cast

import api_client_core.endpoints.utils.endpoint_model as core_endpoint_model_util
from api_client_core.endpoints.endpoint_func import AsyncEndpointFunc as _AsyncEndpointFunc
from api_client_core.endpoints.endpoint_func import EndpointFunc as _EndpointFunc
from api_client_core.endpoints.endpoint_func import SyncEndpointFunc as _SyncEndpointFunc
from api_client_core.types import EndpointModel as _CoreEndpointModel
from common_libs.ansi_colors import ColorCodes, color

import openapi_test_client.libraries.utils.param_model as param_model_util
from openapi_test_client.libraries.endpoints.endpoint import Endpoint
from openapi_test_client.libraries.types import EndpointModel

__all__ = ["AsyncEndpointFunc", "EndpointFunc", "SyncEndpointFunc"]

P = ParamSpec("P")


class EndpointFunc(_EndpointFunc[P]):
    """EndpointFunc subclass with OpenAPI-specific helpers

    See the core's `EndpointFunc` class for details.
    """

    # Type-only re-annotation: narrows the inherited `endpoint` attribute to ours
    endpoint: Endpoint[P]

    @property
    def model(self) -> type[EndpointModel]:
        return cast(type[EndpointModel], super().model)

    def docs(self) -> None:
        """Display OpenAPI spec definition for this endpoint."""
        if api_spec_definition := self.get_usage():
            print(color(api_spec_definition, color_code=ColorCodes.YELLOW))  # noqa: T201
        else:
            print("Docs not available")  # noqa: T201

    def get_usage(self) -> str | None:
        """Get OpenAPI spec definition for the endpoint."""
        if self.api_client and self.endpoint.is_documented:
            api_spec = getattr(self.api_client, "api_spec", None)
            if api_spec is not None:
                return api_spec.get_endpoint_usage(self.endpoint)

    def _create_model(self) -> type[EndpointModel]:
        """Create the endpoint model using the OpenAPI-aware field-name sanitizer.

        Overrides the core implementation to inject the richer OpenAPI sanitizer, which additionally
        covers OpenAPI annotation type names (Format, Constraint, ParamModel, …), dict method names,
        and OpenAPI-specific control kwargs (validate, …) that must never be used as API parameter names.
        """
        return cast(
            type[EndpointModel],
            core_endpoint_model_util.create_endpoint_model(
                self,
                field_name_sanitizer=param_model_util.alias_illegal_model_field_names,
                # mypy treats EndpointModel as abstract here since it descends from a Protocol
                # (DataclassModel). The cast is safe since it's a plain concrete dataclass base.
                model_base=cast(type[_CoreEndpointModel], EndpointModel),
            ),
        )


class SyncEndpointFunc(EndpointFunc[P], _SyncEndpointFunc[P]):
    """Sync endpoint function with OpenAPI-specific helpers."""


class AsyncEndpointFunc(EndpointFunc[P], _AsyncEndpointFunc[P]):
    """Async endpoint function with OpenAPI-specific helpers."""
