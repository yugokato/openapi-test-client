from __future__ import annotations

import inspect
from dataclasses import Field, field, make_dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Annotated, Any, ForwardRef, Literal, Optional, Union, Unpack, cast

import inflect
from common_libs.logging import get_logger
from common_libs.utils import clean_obj_name

import openapi_test_client.libraries.core.endpoints.utils.param_type as param_type_util
from openapi_test_client.libraries.common.misc import generate_class_name
from openapi_test_client.libraries.core.types import (
    Alias,
    DataclassModel,
    DataclassModelField,
    EndpointModel,
    File,
    Kwargs,
    ParamAnnotationType,
    ParamDef,
    ParamModel,
    Unset,
)

logger = get_logger(__name__)


def get_param_model_name(param_model: type[ParamModel] | ForwardRef) -> str:
    """Get the model name

    :param param_model: Param model. This can be a forward ref
    """
    if not param_type_util.is_param_model(param_model):
        raise ValueError(f"{param_model} is not a param model")

    if isinstance(param_model, ForwardRef):
        return param_model.__forward_arg__
    else:
        return param_model.__name__


@lru_cache
def generate_model_name(base_name: str) -> str:
    """Generate model name

    :param base_name: A base name to be used to generate the model name
    """
    model_name = generate_class_name(clean_model_field_name(base_name))
    # Adjust the model name if it happens to conflict with class names we might import
    if model_name in get_reserved_model_names():
        model_name += "_"
    return model_name


@lru_cache
def generate_model_name_for_dataclass_field(field_name: str, is_list: bool = False) -> str:
    """Generate model name from the given parameter

    :param field_name: Dataclass field name
    :param is_list: This is a list type field
    """
    model_name = generate_class_name(clean_model_field_name(field_name))
    # NOTE: You may need to add a custom blacklist/rules for your app in here to ignore words that inflect library
    # doesn't handle well.
    # E.g. The word "bps" (Bits per second) is not a plural word, but inflect thinks it is and incorrectly generates
    # its singular noun as "bp"
    if is_list and (singular_noun := inflect.engine().singular_noun(model_name)):
        # Change the plural model name to the singular word
        model_name = cast(str, singular_noun)

    # Adjust the model name if it happens to conflict with class names we might import, or with the field_name itself
    if model_name in [*get_reserved_model_names(), field_name]:
        model_name += "_"

    return model_name


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
def create_model_from_param_def(
    model_name: str,
    param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType,
    _root: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType | None = None,
) -> type[ParamModel]:
    """Create a model for the parameter from OpenAPI parameter definition

    :param model_name: The model name
    :param param_def: ParamDef generated from an OpenAPI parameter object
    :param _root: For internal use only. The root param def object set when called recursively.
                  This makes sure that lru_cache works with the same models with different versions
    """
    if _root is None:
        _root = param_def

    if not isinstance(param_def, ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType):
        raise ValueError(f"Invalid param_def type: {type(param_def)}")

    if isinstance(param_def, ParamDef) and param_def.is_array and "items" in param_def:
        return create_model_from_param_def(model_name, param_def["items"], _root=_root)
    elif isinstance(param_def, ParamDef.ParamGroup):
        return merge_models(*[create_model_from_param_def(model_name, p, _root=_root) for p in param_def])
    else:
        fields = [
            DataclassModelField(
                inner_param_name,
                param_type_util.resolve_type_annotation(inner_param_name, ParamDef.from_param_obj(inner_param_obj)),
                default=field(default=Unset, metadata=inner_param_obj),
            )
            for inner_param_name, inner_param_obj in param_def.get("properties", {}).items()
        ]
        alias_illegal_model_field_names(model_name, fields)
        return cast(type[ParamModel], make_dataclass(model_name, fields, bases=(ParamModel,)))


def get_param_models(model: type[EndpointModel | ParamModel], recursive: bool = True) -> list[type[ParamModel]]:
    """Get param models defined as the given model's fields

    :param model: Endpoint model or param model
    :param recursive: Recursively collect param models
    """

    def collect_param_models(model: type[EndpointModel | ParamModel]) -> None:
        for field_name, field_obj in model.__dataclass_fields__.items():
            if param_type_util.has_param_model(field_obj.type):
                annotated_param_models = param_type_util.get_param_model(field_obj.type)
                assert annotated_param_models
                if not isinstance(annotated_param_models, list):
                    annotated_param_models = [annotated_param_models]

                param_models = []
                for m in annotated_param_models:
                    if isinstance(m, ForwardRef):
                        param_def = ParamDef.from_param_obj(field_obj.metadata)
                        m = create_model_from_param_def(m.__forward_arg__, param_def)
                    param_models.append(m)
                collected_param_models.extend(param_models)
                if recursive:
                    for m in param_models:
                        collect_param_models(m)

    collected_param_models: list[type[ParamModel]] = []
    collect_param_models(model)
    return collected_param_models


@lru_cache
def clean_model_field_name(name: str) -> str:
    """Returns an alias name if the given name is illegal as a model field name"""
    name = clean_obj_name(name)
    if name in (*get_reserved_model_names(), *get_reserved_param_names(), *dir(dict)):
        # The field name conflicts with one of reserved names
        name += "_"
    return name


@lru_cache
def get_reserved_param_names() -> list[str]:
    """Get list of reserved parameter names that will conflict with the endpoint function's __call__ method"""
    from openapi_test_client.libraries.core import EndpointFunc

    sig_params = inspect.signature(EndpointFunc.__call__).parameters
    return [k for k, v in sig_params.items() if v.kind == v.KEYWORD_ONLY]


def alias_illegal_model_field_names(location: str, model_fields: list[DataclassModelField]) -> None:
    """Clean illegal model field name and annotate the field type with Alias class

    :param location: Location where the field is seen. This is used for logging purpose
    :param model_fields: fields value to be passed to make_dataclass()
    """

    def make_alias(name: str, param_type: Any) -> str:
        if (
            (name == "json" and param_type_util.is_type_of(param_type, list))
            or (name == "data" and param_type_util.is_type_of(param_type, str))
            or (name == "files" and param_type_util.is_type_of(param_type, File))
        ):
            return name
        else:
            name = clean_model_field_name(name)
            if param_models := param_type_util.get_param_model(param_type):
                # There seems to be some known issues when the field name clashes with the type annotation name.
                # We change the field name in this case
                # eg. https://docs.pydantic.dev/2.10/errors/usage_errors/#unevaluable-type-annotation
                if not isinstance(param_models, list):
                    param_models = [param_models]
                if any(name == get_param_model_name(m) for m in param_models):
                    name += "_"
            return name

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


@lru_cache
def merge_models(*models: type[ParamModel]) -> type[ParamModel]:
    """Merge multiple modes that have the same model name with different fields into one new model

    :param models: Param models (Each model must have the same model name)

    Example:

    - Model1
        @dataclass
        class MyModel(ParamModel):
            param_1: str = Unset
            param_2: int = Unset
            param_3: Literal["1", "2"] = Unset

    - Model2
        @dataclass
        class MyModel(ParamModel):
            param_1: str = Unset
            param_2: str = Unset
            param_3: Literal["2", "3"] = Unset
            param_4: int = Unset

    - Merged model
        @dataclass
        class MyModel(ParamModel):
            param_1: str = Unset
            param_2: int | str = Unset
            param_3: Literal["1", "2", "3"] = Unset
            param_4: int = Unset
    """
    assert models
    assert len(set(m.__name__ for m in models)) == 1
    merged_dataclass_fields: dict[str, Field] = {}
    for model in models:
        for field_name, field_obj in model.__dataclass_fields__.items():
            if field_name in merged_dataclass_fields:
                merged_field_obj = merged_dataclass_fields[field_name]
                if merged_field_obj.type != field_obj.type:
                    # merge field types and metadata
                    merged_field_obj.type = param_type_util.merge_annotation_types(
                        merged_field_obj.type, field_obj.type
                    )
                    if "anyOf" in merged_field_obj.metadata:
                        # This is a temporary solution
                        anyOf = merged_field_obj.metadata["anyOf"]
                        if isinstance(anyOf, list):
                            anyOf.append(field_obj.metadata)
                        elif isinstance(anyOf, tuple):
                            metadata = dict(merged_field_obj.metadata)
                            metadata["anyOf"] = (*anyOf, field_obj.metadata)
                            merged_field_obj.metadata = MappingProxyType(metadata)
                        else:
                            raise NotImplementedError(f"Unsupported type of 'anyOf' data: {type(anyOf)}")
                    else:
                        merged_field_obj.metadata = MappingProxyType(
                            {"anyOf": [merged_field_obj.metadata, field_obj.metadata]}
                        )
            else:
                merged_dataclass_fields[field_name] = field_obj

    new_fields = [
        (field_name, field_obj.type, field(default=Unset, metadata=dict(field_obj.metadata)))
        for field_name, field_obj in merged_dataclass_fields.items()
    ]
    return cast(type[ParamModel], make_dataclass(models[0].__name__, new_fields, bases=(ParamModel,)))
