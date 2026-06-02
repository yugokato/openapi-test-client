from __future__ import annotations

import inspect
import typing
from collections.abc import Callable, Mapping
from dataclasses import MISSING, Field, field, make_dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Union, Unpack, cast, get_type_hints

from common_libs.logging import get_logger
from common_libs.naming import clean_obj_name

from ..types import (
    Alias,
    DataclassModel,
    DataclassModelField,
    EndpointModel,
    File,
    Kwargs,
    ParamAnnotationType,
    Unset,
)
from . import endpoint_call as endpoint_call_util
from . import param_type as param_type_util

if TYPE_CHECKING:
    from .. import EndpointFunc


logger = get_logger(__name__)


def create_endpoint_model(
    endpoint_func: EndpointFunc[Any],
    field_name_sanitizer: Callable[[str, list[DataclassModelField]], None] | None = None,
) -> type[EndpointModel]:
    """Create a model class for the endpoint from the current function signature.

    Path parameters are identified by matching their names against the `{placeholder}` tokens in the endpoint path.
    All remaining parameters are treated as body or query parameters.

    :param endpoint_func: Endpoint function for the endpoint
    :param field_name_sanitizer: A callable with the signature `(location, list of DataclassModelField)` that
                                 aliases illegal or reserved field names in-place. Defaults to the core implementation.
                                 Higher layers can inject a richer sanitizer that covers additional reserved names.
    """
    path_param_names = endpoint_call_util.get_path_param_names(endpoint_func.path)

    path_param_fields: list[DataclassModelField] = []
    body_or_query_param_fields: list[DataclassModelField] = []
    try:
        resolved_hints = typing.get_type_hints(endpoint_func._original_func, include_extras=True)
    except Exception as e:
        func_name = f"{endpoint_func._owner.__name__}.{endpoint_func._original_func.__name__}"
        logger.warning(f"[{func_name}]: Failed to resolve type hints: {e}. Falling back to unresolved annotations.")
        resolved_hints = {}
    sig = inspect.signature(endpoint_func._original_func)
    for name, param_obj in sig.parameters.items():
        if name == "self" or param_obj.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        annotation = resolved_hints.get(name, param_obj.annotation)
        if name in path_param_names:
            sig_default = param_obj.default
            if sig_default is inspect.Parameter.empty:
                path_field = field(default=MISSING, metadata={"path": True})
            else:
                path_field = field(default=sig_default, metadata={"path": True})
            path_param_fields.append(DataclassModelField(name, annotation, path_field))
        else:
            # Unset (not MISSING) so callers can omit the param entirely, enabling negative-path testing
            default = param_obj.default if param_obj.default is not inspect.Parameter.empty else Unset
            add_body_or_query_param_field(body_or_query_param_fields, name, annotation, default=default)
    return build_endpoint_model(
        endpoint_func, path_param_fields, body_or_query_param_fields, field_name_sanitizer=field_name_sanitizer
    )


def build_endpoint_model(
    endpoint_func: EndpointFunc[Any],
    path_param_fields: list[DataclassModelField],
    body_or_query_param_fields: list[DataclassModelField],
    content_type: str | None = None,
    field_name_sanitizer: Callable[[str, list[DataclassModelField]], None] | None = None,
) -> type[EndpointModel]:
    """Build an EndpointModel from prepared field lists.

    Shared tail used by both the signature path (create_endpoint_model) and any alternative
    field-source builder a higher layer injects.

    :param endpoint_func: Endpoint function for the endpoint
    :param path_param_fields: Path parameter fields
    :param body_or_query_param_fields: Body or query parameter fields
    :param content_type: Request content type, if known by the caller
    :param field_name_sanitizer: A callable with the signature `(location, list of DataclassModelField)` that
                                 aliases illegal or reserved field names in-place. Defaults to the core implementation.
    """
    _alias_field_names = field_name_sanitizer if field_name_sanitizer is not None else alias_illegal_model_field_names

    model_name = f"{type(endpoint_func).__name__.replace('EndpointFunc', EndpointModel.__name__)}"

    # Address the case where a path param name conflicts with body/query param name
    for i, (field_name, field_type, field_default) in enumerate(path_param_fields):
        if field_name in [x[0] for x in body_or_query_param_fields]:
            path_param_fields[i] = DataclassModelField(f"{field_name}_", field_type, field_default)

    # Some parameter names use characters that are illegal as Python variable names.
    # We will use the cleaned name as the model field and annotate it as `Annotated[field_type, Alias(<original_val>)]`
    # When calling an endpoint function, the actual name will be automatically resolved in the payload/query parameters
    endpoint = f"{endpoint_func.method.upper()} {endpoint_func.path}"
    _alias_field_names(endpoint, path_param_fields)
    _alias_field_names(endpoint, body_or_query_param_fields)

    fields = path_param_fields + body_or_query_param_fields
    return cast(
        type[EndpointModel],
        make_dataclass(
            model_name,
            fields,
            bases=(EndpointModel,),
            namespace={"content_type": content_type, "endpoint_func": endpoint_func},
            kw_only=True,
            frozen=True,
        ),
    )


@lru_cache
def clean_model_field_name(name: str) -> str:
    """Returns an alias name if the given name is illegal as a model field name"""
    name = clean_obj_name(name)
    if name in (*get_reserved_model_names(), *get_reserved_param_names()):
        # The field name conflicts with one of reserved names
        name += "_"
    return name


@lru_cache
def get_reserved_model_names() -> list[str]:
    """Get list of model names that will conflict with what we use"""
    mod = inspect.getmodule(ParamAnnotationType)
    custom_param_annotation_names = [
        x.__name__
        for x in mod.__dict__.values()
        if inspect.isclass(x) and issubclass(x, ParamAnnotationType | DataclassModel)
    ] + ["Unset", Kwargs.__name__]
    typing_class_names = [x.__name__ for x in [Any, Optional, Annotated, Literal, Union, Unpack]]  # type: ignore[attr-defined]
    return custom_param_annotation_names + typing_class_names


@lru_cache
def get_reserved_param_names() -> list[str]:
    """Get list of reserved control kwarg names that must not be used as endpoint parameter names."""
    return list(get_type_hints(Kwargs))


def is_httpx_passthrough_field(name: str, param_type: Any) -> bool:
    """Check if a parameter field should be passed through to httpx unchanged (no aliasing).

    `json`, `data`, and `files` map directly to httpx request kwargs; they must not be
    renamed so the HTTP layer can route them to the correct request slot.

    :param name: Parameter name
    :param param_type: Parameter type annotation
    """
    return (
        (name == "json" and param_type_util.is_type_of(param_type, list))
        or (name == "data" and param_type_util.is_type_of(param_type, str))
        or (name == "files" and param_type_util.is_type_of(param_type, File))
    )


def alias_illegal_model_field_names(location: str, model_fields: list[DataclassModelField]) -> None:
    """Clean illegal model field name and annotate the field type with Alias class

    :param location: Location where the field is seen. This is used for logging purpose
    :param model_fields: fields value to be passed to make_dataclass()
    """

    def make_alias(name: str, param_type: Any) -> str:
        if is_httpx_passthrough_field(name, param_type):
            return name
        return clean_model_field_name(name)

    if model_fields:
        for i, model_field in enumerate(model_fields):
            if (alias_name := make_alias(model_field.name, model_field.type)) != model_field.name:
                if isinstance(model_field.default, Field) and model_field.default.metadata:
                    logger.warning(
                        f"[{location}]: The parameter name '{model_field.name}' was aliased to '{alias_name}'"
                    )
                new_fields = (
                    alias_name,
                    param_type_util.annotate_type(model_field.type, Alias(model_field.name)),
                    model_field.default,
                )
                model_fields[i] = DataclassModelField(*new_fields)


def add_body_or_query_param_field(
    param_fields: list[DataclassModelField],
    param_name: str,
    param_type_annotation: Any,
    metadata: Mapping[str, Any] | dict[str, Any] | None = None,
    default: Any = None,
) -> None:
    if param_name not in [x[0] for x in param_fields]:
        param_fields.append(
            DataclassModelField(param_name, param_type_annotation, default=field(default=default, metadata=metadata))
        )
