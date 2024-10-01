import ipaddress
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import EllipsisType
from typing import Any, TypeVar, get_origin
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    Base64Bytes,
    Base64Str,
    Base64UrlBytes,
    Base64UrlStr,
    EmailStr,
    Field,
    IPvAnyAddress,
    IPvAnyInterface,
    IPvAnyNetwork,
    NameEmail,
)
from pydantic.fields import FieldInfo
from pydantic_extra_types.phone_numbers import PhoneNumber

import openapi_test_client.libraries.api.api_functions.utils.param_model as param_model_util
import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
from openapi_test_client.libraries.api.types import Constraint, DataclassModel, EndpointModel, Format, ParamModel

T = TypeVar("T")


# TODO: Update this if needed
PARAM_FORMAT_AND_TYPE_MAP = {
    "uuid": UUID,
    "date-time": datetime,
    "date": date,
    "time": time,
    "duration": timedelta,
    "binary": bytes,
    "byte": bytes,
    "path": Path,
    "base64": Base64Str | Base64Bytes,
    "base64url": Base64UrlStr | Base64UrlBytes,
    "email": EmailStr,
    "name-email": NameEmail,
    "uri": AnyHttpUrl,
    "ipv4": ipaddress.IPv4Address,
    "ipv6": ipaddress.IPv6Address,
    "ipvanyaddress": IPvAnyAddress,
    "ipvanyinterface": IPvAnyInterface,
    "ipvanynetwork": IPvAnyNetwork,
    "phone": PhoneNumber,
}


def is_validation_mode() -> bool:
    """Check if we are currently in validation mode"""
    return os.environ.get("VALIDATION_MODE", "false").lower() in ["true", "1"]


@contextmanager
def in_validation_mode():
    """Temporarily enable validation mode"""
    if not is_validation_mode():
        os.environ["VALIDATION_MODE"] = "true"
    try:
        yield
    finally:
        del os.environ["VALIDATION_MODE"]


def generate_pydantic_model_fields(
    original_model: type[DataclassModel | EndpointModel | ParamModel], field_type: Any
) -> tuple[str, EllipsisType | FieldInfo | None]:
    """Generate Pydantic field definition for validation mode

    :param original_model: The original model
    :param field_type: The original dataclass field type
    """
    is_query_param = False

    # Convert nested param models to Pydantic models and replace it in the original field type
    if param_model := param_model_util.get_param_model(field_type):
        if isinstance(param_model, list):
            models = [m.to_pydantic() for m in param_model]
            pydantic_model_type = param_type_util.generate_union_type(models)
        else:
            pydantic_model_type = param_model.to_pydantic()
        field_type = param_type_util.replace_inner_type(field_type, pydantic_model_type)

    # Adjust field type and value
    if param_type_util.is_optional_type(field_type):
        default_value = None
    else:
        default_value = ...
    field_value = default_value
    if annotated_type := param_type_util.get_annotated_type(field_type):
        if "query" in annotated_type.__metadata__:
            is_query_param = True

        # Adjust field type based on the param format
        if format := filter_annotated_metadata(annotated_type, Format):
            field_type = convert_type_from_param_format(field_type, format.value)

        # Adjust field value based on the param constraints
        if constraint := filter_annotated_metadata(annotated_type, Constraint):
            if param_type_util.is_type_of(field_type, str):
                const = {}
                if constraint.min_len:
                    const.update(min_length=constraint.min_len)
                if constraint.max_len:
                    const.update(max_length=constraint.max_len)
                if constraint.pattern:
                    const.update(pattern=constraint.pattern)
                field_value = Field(default_value, **const)
            elif param_type_util.is_type_of(field_type, int):
                const = {}
                # TODO: Update the logic around exclusive_minimum/exclusive_maximum once Pydantic starts treating them
                #  as a boolean
                if constraint.exclusive_minimum:
                    const.update(gt=constraint.exclusive_minimum)
                else:
                    const.update(ge=constraint.min)
                if constraint.exclusive_maximum:
                    const.update(lt=constraint.exclusive_maximum)
                else:
                    const.update(le=constraint.max)
                if constraint.multiple_of:
                    const.update(multiple_of=constraint.multiple_of)
                field_value = Field(default_value, **const)
            elif param_type_util.is_type_of(field_type, list):
                field_value = Field(default_value, min_length=constraint.min_len, max_length=constraint.max_len)

            if default_value is not None and constraint.nullable:
                # Required and nullable = Optional
                field_type = field_type | None

        # For query parameters,each parameter may be allowed to use multiple times with different values. Our client
        # will support this scenario by taking values as a list. To prevent a validation error to occur when giving a
        # list, adjust the model type to also allow list.
        if is_query_param or (
            issubclass(original_model, EndpointModel) and original_model.endpoint_func.method.upper() == "GET"
        ):
            inner_type = param_type_util.get_inner_type(field_type)
            if get_origin(inner_type) is not list:
                field_type = param_type_util.replace_inner_type(field_type, inner_type | list[inner_type])

    return (field_type, field_value)


def filter_annotated_metadata(annotated_type: Any, target_class: type[T]) -> T | None:
    """Get a metadata for the target class from annotated type

    :param annotated_type: Type annotation with Annotated[]
    :param target_class: Specify which metadata to return
    """
    metadata = annotated_type.__metadata__
    filtered_meta = [x for x in metadata if isinstance(x, target_class)]
    if filtered_meta:
        assert len(filtered_meta) == 1
        return filtered_meta[0]


def convert_type_from_param_format(field_type: Any, format: str) -> Any:
    """Convert field type based on the parameter format, if applicable

    :param field_type: Current field type
    :param format: OpenAPI parameter format
    """
    if pydantic_type := PARAM_FORMAT_AND_TYPE_MAP.get(format):
        return param_type_util.replace_inner_type(field_type, pydantic_type)
    else:
        return field_type
