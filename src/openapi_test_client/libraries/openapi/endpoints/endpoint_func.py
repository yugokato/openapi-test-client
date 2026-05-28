"""OpenAPI-specific endpoint function classes."""

from __future__ import annotations

from common_libs.ansi_colors import ColorCodes, color

import openapi_test_client.libraries.core.utils.endpoint_model as core_endpoint_model_util
import openapi_test_client.libraries.openapi.utils.param_model as param_model_util
from openapi_test_client.libraries.core.endpoints.endpoint_func import AsyncEndpointFunc as _AsyncEndpointFunc
from openapi_test_client.libraries.core.endpoints.endpoint_func import EndpointFunc as _EndpointFunc
from openapi_test_client.libraries.core.endpoints.endpoint_func import SyncEndpointFunc as _SyncEndpointFunc
from openapi_test_client.libraries.openapi.types import EndpointModel

__all__ = ["AsyncEndpointFunc", "EndpointFunc", "SyncEndpointFunc"]


class EndpointFunc(_EndpointFunc):
    """EndpointFunc subclass with OpenAPI-specific helpers (docs, get_usage)."""

    @property
    def model(self) -> type[EndpointModel]:
        """Return the dynamically created model of the endpoint, using the OpenAPI-aware field-name sanitizer.

        Overrides the core implementation to inject the richer OpenAPI sanitizer, which additionally
        covers OpenAPI annotation type names (Format, Constraint, ParamModel, …), dict method names,
        and OpenAPI-specific control kwargs (validate, …) that must never be used as API parameter names.
        """
        return core_endpoint_model_util.create_endpoint_model(
            self, field_name_sanitizer=param_model_util.alias_illegal_model_field_names
        )

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


class SyncEndpointFunc(EndpointFunc, _SyncEndpointFunc):
    """Sync endpoint function with OpenAPI-specific helpers."""


class AsyncEndpointFunc(EndpointFunc, _AsyncEndpointFunc):
    """Async endpoint function with OpenAPI-specific helpers."""
