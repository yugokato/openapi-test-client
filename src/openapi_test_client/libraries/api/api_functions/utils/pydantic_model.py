import inspect
import ipaddress
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import Field as DataclassField
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import EllipsisType
from typing import Any, TypeVar, get_args
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
def in_validation_mode() -> Generator[None, Any, None]:
    """Temporarily enable validation mode"""
    if not is_validation_mode():
        os.environ["VALIDATION_MODE"] = "true"
    try:
        yield
    finally:
        del os.environ["VALIDATION_MODE"]


def generate_pydantic_model_field(
    original_model: type[DataclassModel | EndpointModel | ParamModel], model_field: DataclassField
) -> tuple[Any, EllipsisType | None]:
    """Generate Pydantic field definition for validation mode

    :param original_model: The original dataclass model
    :param model_field: The model field obj
    """
    if isinstance(model_field.type, str):
        # Resolve forward reference
        model_field.type = inspect.get_annotations(original_model, eval_str=True)[model_field.name]

    if param_type_util.is_optional_type(model_field.type):
        default_value = None
    else:
        default_value = ...

    if param_type_util.is_union_type(model_field.type):
        dataclass_field_types = get_args(model_field.type)
    else:
        dataclass_field_types = (model_field.type,)

    pydantic_field_types = []
    for dataclass_field_type in dataclass_field_types:
        # Convert nested param models to Pydantic models and replace it in the original field type
        if param_model := param_model_util.get_param_model(dataclass_field_type):
            if isinstance(param_model, list):
                models = [m.to_pydantic() for m in param_model]
                pydantic_model_type = param_type_util.generate_union_type(models)
            else:
                pydantic_model_type = param_model.to_pydantic()
            dataclass_field_type = param_type_util.replace_base_type(dataclass_field_type, pydantic_model_type)

        if annotated_type := param_type_util.get_annotated_type(dataclass_field_type):
            if isinstance(annotated_type, list | tuple):
                # This should not happen since we are looping through each type if the field type is union
                raise NotImplementedError(f"Unsupported field type for validation mode: '{model_field.type}'")

            base_type = param_type_util.get_base_type(annotated_type)
            is_query_param = "query" in annotated_type.__metadata__

            # Adjust field type based on the param format
            if format := filter_annotated_metadata(annotated_type, Format):
                base_type = convert_type_from_param_format(base_type, format.value)

            # Add pydantic Field objectbased on the param constraints
            # NOTE: If the field type was converted to a validation type provided by Pydantic (eg. str->EmailStr), the
            # following constraint will be ignored (Pydantic doesn't allow extra options to be added to a Field object).
            # We will completely rely on Pydantic's validation logic in this case.
            if constraint := filter_annotated_metadata(annotated_type, Constraint):
                const: dict[str, Any] = {}
                if param_type_util.is_type_of(base_type, str):
                    if constraint.min_len:
                        const.update(min_length=constraint.min_len)
                    if constraint.max_len:
                        const.update(max_length=constraint.max_len)
                    if constraint.pattern:
                        const.update(pattern=constraint.pattern)
                elif param_type_util.is_type_of(base_type, int):
                    # TODO: Update the logic around exclusive_minimum/exclusive_maximum once Pydantic starts treating
                    #  them as a boolean
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
                elif param_type_util.is_type_of(base_type, list):
                    const.update(min_length=constraint.min_len, max_length=constraint.max_len)

                if const:
                    # Update metadata: remove Constraint and add Field
                    new_metadata = [x for x in annotated_type.__metadata__ if not isinstance(x, Constraint)] + [
                        Field(**const)
                    ]
                    dataclass_field_type = param_type_util.modify_annotated_metadata(
                        annotated_type, *new_metadata, action="replace"
                    )

                if default_value is not None and constraint.nullable:
                    # Required and nullable = Optional
                    base_type = base_type | None

            dataclass_field_type = param_type_util.replace_base_type(dataclass_field_type, base_type)

            # For query parameters, each parameter may be allowed to use multiple times with different values.
            # Our client will support this scenario by taking values as a list. To prevent a validation error to
            # occur when giving a list, adjust the model type to also allow list.
            if is_query_param or (
                issubclass(original_model, EndpointModel) and original_model.endpoint_func.method.upper() == "GET"
            ):
                base_type = param_type_util.get_base_type(dataclass_field_type)
                if not param_type_util.is_type_of(base_type, list):
                    dataclass_field_type = param_type_util.replace_base_type(
                        dataclass_field_type,
                        base_type | list[base_type],  # type: ignore[valid-type]
                    )
        pydantic_field_types.append(dataclass_field_type)

    return (param_type_util.generate_union_type(pydantic_field_types), default_value)


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
        return param_type_util.replace_base_type(field_type, pydantic_type)
    else:
        return field_type
