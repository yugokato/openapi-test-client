from __future__ import annotations

import inspect
from collections import defaultdict
from dataclasses import Field, field, make_dataclass
from functools import lru_cache
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Union, cast, get_args, get_origin

import inflect
from common_libs.clients.rest_client.utils import get_supported_request_parameters
from common_libs.logging import get_logger
from common_libs.utils import clean_obj_name

import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
import openapi_test_client.libraries.api.types as types_module
from openapi_test_client.libraries.api.types import (
    Alias,
    DataclassModel,
    EndpointModel,
    File,
    ParamAnnotationType,
    ParamDef,
    ParamModel,
    Unset,
)
from openapi_test_client.libraries.common.constants import TAB
from openapi_test_client.libraries.common.misc import generate_class_name

if TYPE_CHECKING:
    from openapi_test_client.libraries.api import APIClassType


logger = get_logger(__name__)


def has_param_model(annotated_type: Any) -> bool:
    """Check if the given annotated type contains a custom param model

    :param annotated_type: Annotated type for a field to check whether it contains a param model or not
    """

    def _is_param_model(obj: Any) -> bool:
        return inspect.isclass(obj) and issubclass(obj, ParamModel)

    inner_type = param_type_util.get_inner_type(annotated_type)
    if param_type_util.is_union_type(inner_type):
        return any(_is_param_model(o) for o in get_args(inner_type))
    else:
        return _is_param_model(inner_type)


def get_param_model(annotated_type: Any) -> ParamModel | list[ParamModel] | None:
    """Returns a param model from the annotated type, if there is any

    :param annotated_type: Annotated type
    """
    inner_type = param_type_util.get_inner_type(annotated_type)
    if has_param_model(inner_type):
        if param_type_util.is_union_type(inner_type):
            return [x for x in get_args(inner_type) if has_param_model(x)]
        else:
            return inner_type


@lru_cache
def generate_model_name(field_name: str, field_type: str | Any) -> str:
    """Generate model name from the given field

    :param field_name: Dataclass field name
    :param field_type: OpenAPI parameter type or dataclass field type
    """
    model_name = generate_class_name(field_name)
    # NOTE: You may need to add a custom blacklist/rules for your app in here to ignore words that inflect library
    # doesn't handle well.
    # Eg. The word "bps" (Bits per second) is not a plural word, but inflect thinks it is and incorrectly generates
    # its singular noun as "bp"
    if param_type_util.is_type_of(field_type, list) and (singular_noun := inflect.engine().singular_noun(model_name)):
        # Change the plural model name to the singular word
        model_name = singular_noun

    # Adjust the model name if it happens to conflict with class names we might import, or with the field_name itself
    if model_name in [*get_reserved_model_names(), field_name]:
        model_name += "_"

    return model_name  # type:ignore


@lru_cache
def get_reserved_model_names() -> list[str]:
    """Get list of model names that will conflict with what we use"""
    mod = inspect.getmodule(ParamAnnotationType)
    custom_param_annotation_names = [
        x.__name__
        for x in mod.__dict__.values()
        if inspect.isclass(x) and issubclass(x, ParamAnnotationType | DataclassModel)
    ] + ["Unset"]
    typing_class_names = [x.__name__ for x in [Any, Optional, Annotated, Literal, Union]]
    return custom_param_annotation_names + typing_class_names


@lru_cache
def create_model_from_param_def(
    model_name: str, param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType
) -> type[ParamModel]:
    """Create a model for the parameter from OpenAPI parameter definition

    :param model_name: The model name
    :param param_def: ParamDef generated from an OpenAPI parameter object
    """
    if not isinstance(param_def, ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType):
        raise ValueError(f"Invalid param_def type: {type(param_def)}")

    if isinstance(param_def, ParamDef) and param_def.is_array and "items" in param_def:
        return create_model_from_param_def(model_name, param_def["items"])
    elif isinstance(param_def, ParamDef.ParamGroup):
        return _merge_models([create_model_from_param_def(model_name, p) for p in param_def])
    else:
        fields = [
            (
                inner_param_name,
                param_type_util.resolve_type_annotation(inner_param_name, ParamDef.from_param_obj(inner_param_obj)),
                field(default=Unset, metadata=inner_param_obj),
            )
            for inner_param_name, inner_param_obj in param_def.get("properties", {}).items()
        ]
        alias_illegal_model_field_names(fields)
        return cast(type[ParamModel], make_dataclass(model_name, fields, bases=(ParamModel,)))


def generate_imports_code_from_model(
    api_class: type[APIClassType], model: type[EndpointModel | ParamModel], exclude_nested_models: bool = False
) -> str:
    """Generate imports code from the model

    :param api_class: The API class the model is for
    :param model: A dataclass obj
    :param exclude_nested_models: Skip imports for nested models (to avoid define imports for models in the same file)
    """
    imports_code = ""
    module_and_name_pairs = set()
    primitive_types = [int, float, str, bool]
    from openapi_test_client.libraries.api.api_client_generator import API_MODEL_CLASS_DIR_NAME

    def generate_imports_code(obj_type: Any):
        if obj_type not in [*primitive_types, None, NoneType] and not isinstance(obj_type, tuple(primitive_types)):
            if typing_origin := get_origin(obj_type):
                if typing_origin is Annotated:
                    module_and_name_pairs.add(("typing", Annotated.__name__))
                    [generate_imports_code(m) for m in get_args(obj_type)]
                elif typing_origin is Literal:
                    module_and_name_pairs.add(("typing", Literal.__name__))
                elif typing_origin in [list, dict, tuple]:
                    [generate_imports_code(m) for m in [x for x in get_args(obj_type)]]
                elif typing_origin in [UnionType, Union]:
                    if param_type_util.is_optional_type(obj_type):
                        # NOTE: We will use our alias version of typing.Optional for now
                        # module_and_name_pairs.add(("typing", Optional.__name__))
                        module_and_name_pairs.add((types_module.__name__, Optional.__name__))
                    [generate_imports_code(m) for m in get_args(obj_type)]
                else:
                    raise NotImplementedError(f"Unsupported typing origin: {typing_origin}")
            elif has_param_model(obj_type):
                if not exclude_nested_models:
                    api_cls_module, model_file_name = api_class.__module__.rsplit(".", 1)
                    module_and_name_pairs.add(
                        (
                            f"..{API_MODEL_CLASS_DIR_NAME}.{model_file_name}",
                            # Using the original field type here to detect list or not
                            generate_model_name(field_name, field_type),
                        )
                    )
            else:
                if inspect.isclass(obj_type):
                    name = obj_type.__name__
                else:
                    name = type(obj_type).__name__
                module_and_name_pairs.add((obj_type.__module__, name))

    has_unset_field = False
    for field_name, field_obj in model.__dataclass_fields__.items():
        if field_obj.default is Unset:
            has_unset_field = True
        field_type = field_obj.type
        generate_imports_code(field_type)

    if has_unset_field:
        imports_code = _add_unset_import_code(imports_code)

    for module, name in module_and_name_pairs:
        imports_code += f"from {module} import {name}\n"

    return imports_code


def generate_model_code_from_model(api_class: type[APIClassType], model: type[ParamModel]) -> tuple[str, str]:
    """Generate dataclass code from the model

    :param api_class: The API class the model is for
    :param model: A dataclass obj
    """
    model_code = f"@dataclass\nclass {model.__name__}(ParamModel):\n"
    imports_code = generate_imports_code_from_model(api_class, model, exclude_nested_models=True)
    if dataclass_field_items := model.__dataclass_fields__.items():
        imports_code = _add_unset_import_code(imports_code)
        for field_name, field_obj in dataclass_field_items:
            model_code += f"{TAB}{field_name}: {param_type_util.get_type_annotation_as_str(field_obj.type)} = Unset\n"
    else:
        model_code += (
            f"{TAB}# No parameters are documented for this model\n"
            f"{TAB}# The model can take any parameters you want\n"
            f"{TAB}..."
        )
    model_code += "\n"

    return imports_code, model_code


def get_param_models(model: type[EndpointModel | ParamModel], recursive: bool = True) -> list[type[ParamModel]]:
    """Get param models defined as the given model's fields

    :param model: Endpoint model or param model
    :param recursive: Recursively collect param models
    """

    def collect_param_models(model: type[EndpointModel | ParamModel]):
        for field_name, field_obj in model.__dataclass_fields__.items():
            if has_param_model(field_obj.type):
                model_name = generate_model_name(field_name, field_obj.type)
                param_def = ParamDef.from_param_obj(field_obj.metadata)
                param_model = create_model_from_param_def(model_name, param_def)
                param_models.append(param_model)
                if recursive:
                    collect_param_models(param_model)

    param_models = []
    collect_param_models(model)
    return param_models


def dedup_models_by_name(models: list[type[ParamModel]]) -> list[type[ParamModel]]:
    """Dedup models by model name

    :param models: Param models
    """
    models_per_name = defaultdict(list)
    for model in models:
        models_per_name[model.__name__].append(model)

    deduped_models = []
    for models_with_same_name in models_per_name.values():
        deduped_models.append(_merge_models(models_with_same_name))

    return deduped_models


def sort_by_dependency(models: list[type[ParamModel]]) -> list[type[ParamModel]]:
    """Sort param models by dependencies so that Unresolved reference error will not occur when dumping them as
    dataclass mode code.

    :param models: Param models. Each model name MUST be unique. Apply dedup in advance if there are multiple models
                   that have the same name with different fields
    """
    if len([m.__name__ for m in models]) != len(models):
        # Explicitly reject this case to be safe. Dedup should be explicitly done by users
        raise RuntimeError("One or more models unexpectedly have the same model name. Apply dedup if needed")

    nested_model_names = {m.__name__: [x.__name__ for x in get_param_models(m)] for m in models}
    visited_model_names = set()
    sorted_models_names = []

    def visit(model_name: str):
        if model_name not in visited_model_names:
            visited_model_names.add(model_name)
            for nested_model_name in nested_model_names.get(model_name, []):
                visit(nested_model_name)
            if model_name not in sorted_models_names:
                sorted_models_names.append(model_name)

    for model in models:
        visit(model.__name__)
    assert len(models) == len(sorted_models_names)
    return sorted(models, key=lambda x: sorted_models_names.index(x.__name__))


def alias_illegal_model_field_names(param_fields: list[tuple[str, Any] | tuple[str, Any, Field]]):
    """Clean illegal model field name and annotate the field type with Alias class

    :param param_fields: fields value to be passed to make_dataclass()
    """

    def make_alias(name: str, param_type: Any) -> str:
        if (
            (name == "json" and param_type_util.is_type_of(param_type, list))
            or (name == "data" and param_type_util.is_type_of(param_type, str))
            or (name == "files" and param_type_util.is_type_of(param_type, File))
        ):
            return name
        else:
            name = clean_obj_name(name)
            # NOTE: The escaping of kwargs is already is handled in endpoint model
            reserved_param_names = [*get_supported_request_parameters(), "validate"]
            if name in get_reserved_model_names() + reserved_param_names:
                # The field name conflicts with one of reserved names
                name += "_"

            if param_models := get_param_model(param_type):
                # There seems to be an issue with the `Annotated` cache behavior. AttributeError will be thrown on
                # importing the model when the following conditions are all met:
                # - The model field is annotated with `Annotated`
                # - The origin type of `Annotated` is another param model, or union of param models (nested model)
                # - The model field name is identical to one of the annotated model names
                # eg.
                #
                # @dataclass
                # class NestedModel(ParamModel):
                #     param: str = Unset
                #
                # @dataclass
                # class Model(ParamModel):
                #     NestedModel: Annotated[NestedModel, "test"] = Unset
                #
                if not isinstance(param_models, list):
                    param_models = [param_models]
                if any(name == m.__name__ for m in param_models):
                    # This meets the above issue conditions
                    name += "_"
            return name

    if param_fields:
        for i, param_field in enumerate(param_fields):
            if len(param_field) == 2:
                # path parameters
                field_name, field_type = param_field
                field_obj = object
            else:
                # body or query parameters
                field_name, field_type, field_obj = param_field

            if (alias_name := make_alias(field_name, field_type)) != field_name:
                if isinstance(field_obj, Field) and field_obj.metadata:
                    logger.warning(f"Converted parameter name '{field_name}' to '{alias_name}'")
                new_fields = [alias_name, param_type_util.generate_annotated_type(field_type, Alias(field_name))]
                new_fields.append(field_obj)
                param_fields[i] = tuple(new_fields)


def _merge_models(models: list[type[ParamModel]]) -> type[ParamModel]:
    """Merge multiple modes that have the same model name with different fields into one new model

    :param models: Param models (Each model must have the same model name)

    Example:

    - Model1
        @dataclass
        class MyModel:
            param_1: str = Unset
            param_2: int = Unset

    - Model2
        @dataclass
        class MyModel:
            param_1: str = Unset
            param_3: int = Unset

    - Merged model
        @dataclass
        class MyModel:
            param_1: str = Unset
            param_2: int = Unset
            param_3: int = Unset

    """
    assert models
    assert len(set(m.__name__ for m in models)) == 1
    merged_dataclass_fields = {}
    for model in models:
        merged_dataclass_fields.update(model.__dataclass_fields__)
    new_fields = [
        (field_name, field_obj.type, field(default=Unset, metadata=field_obj.metadata))
        for field_name, field_obj in merged_dataclass_fields.items()
    ]
    return cast(type[ParamModel], make_dataclass(models[0].__name__, new_fields, bases=(ParamModel,)))


def _add_unset_import_code(imports_code: str) -> str:
    imports_code += f"from {types_module.__name__} import Unset\n"
    return imports_code
