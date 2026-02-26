from __future__ import annotations

import inspect
from collections import defaultdict
from dataclasses import MISSING, asdict
from types import NoneType, UnionType
from typing import Annotated, Any, ForwardRef, Literal, Optional, Union, get_args, get_origin

from openapi_test_client.libraries.common.constants import BACKSLASH, TAB
from openapi_test_client.libraries.core import APIBase
from openapi_test_client.libraries.core import types as types_module
from openapi_test_client.libraries.core.endpoints.utils.param_model import get_param_models, merge_models
from openapi_test_client.libraries.core.endpoints.utils.param_type import (
    get_param_model,
    has_param_model,
    is_optional_type,
    is_union_type,
)
from openapi_test_client.libraries.core.types import Alias, Constraint, EndpointModel, Format, Kwargs, ParamModel, Unset


def generate_func_signature_code(model: type[EndpointModel]) -> str:
    """Convert model to type annotated function signature code

    :param model: Endpoint model
    """
    model_dataclass_fields = model.__dataclass_fields__
    signatures = ["self"]
    has_path_var = False
    has_params = False
    positional_only_added = False
    for field_name, field_obj in model_dataclass_fields.items():
        is_path_var = field_obj.default is MISSING
        type_annotation = generate_type_annotation_code(field_obj.type)
        if is_path_var:
            has_path_var = True
            sig = f"{field_name}: {type_annotation}"
        else:
            if has_path_var and not positional_only_added:
                signatures.append("/")
            positional_only_added = True
            if not has_params:
                signatures.append("*")
            has_params = True
            sig = f"{field_name}: {type_annotation} = Unset"
        signatures.append(sig)
    if has_path_var and not positional_only_added:
        signatures.append("/")

    kwargs_arg = "**kwargs"
    kwargs_type = f"Unpack[{Kwargs.__name__}]"
    if any("kwargs:" in s for s in signatures):
        kwargs_arg = kwargs_arg + "_"
    signatures.append(f"{kwargs_arg}: {kwargs_type}")
    return ", ".join(signatures)


def generate_imports_code_from_model(
    api_class: type[APIBase], model: type[EndpointModel | ParamModel], exclude_nested_models: bool = False
) -> str:
    """Generate imports code from the model

    :param api_class: The API class the model is for
    :param model: A dataclass obj
    :param exclude_nested_models: Skip imports for nested models (to avoid define imports for models in the same file)
    """
    if issubclass(model, EndpointModel):
        imports_code = f"from typing import Unpack\nfrom {Kwargs.__module__} import {Kwargs.__name__}\n"
    else:
        imports_code = ""
    module_and_name_pairs = set()
    primitive_types = [int, float, str, bool]
    from openapi_test_client.libraries.code_gen.client_generator import API_MODEL_CLASS_DIR_NAME

    def generate_imports_code(obj_type: Any) -> str:
        if obj_type not in [*primitive_types, None, NoneType] and not isinstance(obj_type, tuple(primitive_types)):
            if typing_origin := get_origin(obj_type):
                if typing_origin is Annotated:
                    module_and_name_pairs.add(("typing", Annotated.__name__))  # type: ignore[attr-defined]
                    [generate_imports_code(m) for m in get_args(obj_type)]
                elif typing_origin is Literal:
                    module_and_name_pairs.add(("typing", Literal.__name__))  # type: ignore[attr-defined]
                elif typing_origin in [list, dict, tuple]:
                    [generate_imports_code(m) for m in [x for x in get_args(obj_type)]]
                elif typing_origin in [UnionType, Union]:
                    if is_optional_type(obj_type):
                        # NOTE: We will use our alias version of typing.Optional for now
                        # module_and_name_pairs.add(("typing", Optional.__name__))  # type: ignore[attr-defined]
                        module_and_name_pairs.add((types_module.__name__, Optional.__name__))  # type: ignore[attr-defined]
                    [generate_imports_code(m) for m in get_args(obj_type)]
                else:
                    raise NotImplementedError(f"Unsupported typing origin: {typing_origin}")
            elif has_param_model(obj_type):
                if not exclude_nested_models:
                    _, model_file_name = api_class.__module__.rsplit(".", 1)
                    param_models = get_param_model(obj_type)
                    assert param_models
                    if not isinstance(param_models, list):
                        param_models = [param_models]
                    for m in param_models:
                        model_name = m.__forward_arg__ if isinstance(m, ForwardRef) else m.__name__
                        module_and_name_pairs.add((f"..{API_MODEL_CLASS_DIR_NAME}.{model_file_name}", model_name))
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
        imports_code += f"from {types_module.__name__} import Unset\n"

    for module, name in module_and_name_pairs:
        imports_code += f"from {module} import {name}\n"

    return imports_code


def generate_model_code_from_model(api_class: type[APIBase], model: type[ParamModel]) -> tuple[str, str]:
    """Generate dataclass code from the model

    :param api_class: The API class the model is for
    :param model: A dataclass obj
    """
    model_code = f"@dataclass\nclass {model.__name__}(ParamModel):\n"
    imports_code = (
        f"from __future__ import annotations\n\n"  # workaround for NameError when 2 models depend on each other
        f"{generate_imports_code_from_model(api_class, model, exclude_nested_models=True)}"
    )
    if dataclass_field_items := model.__dataclass_fields__.items():
        for field_name, field_obj in dataclass_field_items:
            model_code += f"{TAB}{field_name}: {generate_type_annotation_code(field_obj.type)} = Unset\n"
    else:
        model_code += (
            f"{TAB}# No parameters are documented for this model\n"
            f"{TAB}# The model can take any parameters you want\n"
            f"{TAB}..."
        )
    model_code += "\n"

    return imports_code, model_code


def generate_type_annotation_code(tp: Any) -> str:
    """Generate type annotation code for the given type

    :param tp: Type annotation
    """
    if isinstance(tp, str):
        return repr(tp)
    elif tp is Ellipsis:
        return "..."
    elif isinstance(tp, ForwardRef):
        return tp.__forward_arg__
    elif get_origin(tp) is Annotated:
        orig_type = generate_type_annotation_code(tp.__origin__)
        metadata_types = ", ".join(generate_type_annotation_code(m) for m in tp.__metadata__)
        return f"{Annotated.__name__}[{orig_type}, {metadata_types}]"  # type: ignore[attr-defined]
    elif is_union_type(tp):
        args = get_args(tp)
        if NoneType in args:
            inner_types = [x for x in args if x is not NoneType]
            if len(inner_types) == 1:
                return f"{Optional.__name__}[{generate_type_annotation_code(inner_types[0])}]"  # type: ignore[attr-defined]
            else:
                inner_types_union = " | ".join(generate_type_annotation_code(x) for x in inner_types)
                # Note: This is actually Union[tp1, ..., None] in Python, but we annotate this as
                # Optional[tp1 | ...] in code
                return f"{Optional.__name__}[{inner_types_union}]"  # type: ignore[attr-defined]
        else:
            return " | ".join(generate_type_annotation_code(x) for x in args)
    elif get_origin(tp) in [list, dict, tuple]:
        args_str: str = ", ".join(generate_type_annotation_code(t) for t in get_args(tp))
        return f"{tp.__origin__.__name__}[{args_str}]"
    elif get_origin(tp) is Literal:
        return repr(tp).replace("typing.", "")
    elif isinstance(tp, Alias | Format):
        return f"{type(tp).__name__}({tp.value!r})"
    elif isinstance(tp, Constraint):
        const = ", ".join(
            f"{k}={('r' + repr(v).replace(BACKSLASH * 2, BACKSLASH) if k == 'pattern' else repr(v))}"
            for k, v in asdict(tp).items()
            if v is not None
        )
        return f"{type(tp).__name__}({const})"
    elif tp in [NoneType, None]:
        return "None"
    else:
        if inspect.isclass(tp):
            return tp.__name__
        else:
            return type(tp).__name__


def dedup_models_by_name(models: list[type[ParamModel]]) -> list[type[ParamModel]]:
    """Dedup models by model name

    :param models: Param models
    """
    models_per_name = defaultdict(list)
    for model in models:
        models_per_name[model.__name__].append(model)

    deduped_models = []
    for models_with_same_name in models_per_name.values():
        deduped_models.append(merge_models(*models_with_same_name))

    return deduped_models


def sort_models_by_dependency(models: list[type[ParamModel]]) -> list[type[ParamModel]]:
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

    def visit(model_name: str) -> None:
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
