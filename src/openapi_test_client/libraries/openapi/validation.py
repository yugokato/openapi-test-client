"""OpenAPI-specific request validator."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from common_libs.ansi_colors import ColorCodes, color
from pydantic import ValidationError

import openapi_test_client.libraries.openapi.utils.pydantic_model as pydantic_model_util

if TYPE_CHECKING:
    from openapi_test_client.libraries.core import Endpoint


class OpenAPIRequestValidator:
    """Validates endpoint request parameters using Pydantic strict mode."""

    def is_validation_mode(self) -> bool:
        """Check if validation mode is active via the VALIDATION_MODE env var."""
        return pydantic_model_util.is_validation_mode()

    def validate(
        self,
        endpoint: Endpoint,
        path_params: tuple[Any, ...],
        body_or_query_params: dict[str, Any],
    ) -> None:
        """Validate endpoint request parameters using Pydantic.

        Both endpoint parameters and nested param models will be validated in strict mode.

        :param endpoint: Endpoint obj
        :param path_params: Request path parameters
        :param body_or_query_params: Request body or query parameters
        """
        path_param_names = (k for k, v in endpoint.model.__dataclass_fields__.items() if v.metadata.get("path"))
        path_params_ = OrderedDict(zip(path_param_names, path_params))
        PydanticEndpointModel = pydantic_model_util.to_pydantic(endpoint.model)
        try:
            PydanticEndpointModel.validate_as_json({**path_params_, **body_or_query_params})
        except ValidationError as e:
            raise ValueError(color(f"Request parameter validation failed.\n{e}", color_code=ColorCodes.RED)) from None
