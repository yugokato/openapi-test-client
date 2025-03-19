from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import asdict
from functools import reduce
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Annotated, Any, ForwardRef, Literal, Optional, Union, get_args, get_origin

from common_libs.logging import get_logger

import openapi_test_client.libraries.api.api_functions.utils.param_model as param_model_util
from openapi_test_client.libraries.api.types import (
    Alias,
    Constraint,
    Format,
    ParamAnnotationType,
    ParamDef,
    UncacheableLiteralArg,
)
from openapi_test_client.libraries.api.types import Optional as Optional_
from openapi_test_client.libraries.common.constants import BACKSLASH
from openapi_test_client.libraries.common.misc import dedup

if TYPE_CHECKING:
    from typing import _AnnotatedAlias, _LiteralGenericAlias  # type: ignore[attr-defined]


logger = get_logger(__name__)


STR_PARAM_TYPES = ["string", "str"]
INT_PARAM_TYPES = ["integer", "int", "int64", "number"]
BOOL_PARAM_TYPES = ["boolean", "bool"]
LIST_PARAM_TYPES = ["array"]
NULL_PARAM_TYPES = ["null"]


def get_type_annotation_as_str(tp: Any) -> str:
    """Get type annotation for the given type as string

    :param tp: Type annotation
    """
    if isinstance(tp, str):
        return repr(tp)
    elif tp is Ellipsis:
        return "..."
    elif isinstance(tp, ForwardRef):
        return tp.__forward_arg__
    elif get_origin(tp) is Annotated:
        orig_type = get_type_annotation_as_str(tp.__origin__)
        metadata_types = ", ".join(get_type_annotation_as_str(m) for m in tp.__metadata__)
        return f"{Annotated.__name__}[{orig_type}, {metadata_types}]"  # type: ignore[attr-defined]
    elif is_union_type(tp):
        args = get_args(tp)
        if NoneType in args:
            inner_types = [x for x in args if x is not NoneType]
            if len(inner_types) == 1:
                return f"{Optional.__name__}[{get_type_annotation_as_str(inner_types[0])}]"  # type: ignore[attr-defined]
            else:
                inner_types_union = " | ".join(get_type_annotation_as_str(x) for x in inner_types)
                # Note: This is actually Union[tp1, ..., None] in Python, but we annotate this as
                # Optional[tp1 | ...] in code
                return f"{Optional.__name__}[{inner_types_union}]"  # type: ignore[attr-defined]
        else:
            return " | ".join(get_type_annotation_as_str(x) for x in args)
    elif get_origin(tp) in [list, dict, tuple]:
        args_str: str = ", ".join(get_type_annotation_as_str(t) for t in get_args(tp))
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


def resolve_type_annotation(
    param_name: str,
    param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType | Any,
    _is_required: bool | None = None,
    _is_array: bool = False,
) -> Any:
    """Resolve type annotation for the given parameter definition

    :param param_name: Parameter name
    :param param_def: Param def
    :param _is_required: Force this parameter required (even if API specs say not required)
    :param _is_array: Indicates that this parameter is a list type
    """

    def resolve(param_type: str, param_format: str | None = None) -> Any:
        """Resolve type annotation

        NOTE: Some OpenAPI spec use a wrong param type value (eg. string v.s. str).
              We handle these scenarios accordingly
        """
        if param_type in STR_PARAM_TYPES:
            if param_format:
                return annotate_type(str, Format(param_format))
            else:
                return str
        elif param_type in INT_PARAM_TYPES:
            if param_type == "number" and param_format == "float":
                return float
            elif param_format:
                return annotate_type(int, Format(param_format))
            else:
                return int
        elif param_type in BOOL_PARAM_TYPES:
            return bool
        elif param_type in NULL_PARAM_TYPES:
            return None
        elif param_type in LIST_PARAM_TYPES:
            assert isinstance(param_def, ParamDef | dict)
            assert param_def.is_array
            try:
                items = param_def["items"]
                if not items:
                    # Somehow empty list
                    return list[Any]
                elif isinstance(items, ParamDef.ParamGroup):
                    return list[
                        generate_union_type(
                            [
                                resolve_type_annotation(param_name, p, _is_required=_is_required, _is_array=True)
                                for p in items
                            ]
                        )
                    ]
                else:
                    return list[resolve_type_annotation(param_name, items, _is_required=_is_required, _is_array=True)]
            except KeyError:
                # Looks like param type for a list item is not always documented properly
                return list[Any]
        elif param_type == "object":
            if "properties" in param_def or param_def.get("__circular_ref__"):
                # Param model
                model_name = param_model_util.generate_model_name(param_name, list if _is_array else Any)
                if "properties" in param_def:
                    return param_model_util.create_model_from_param_def(model_name, param_def)
                else:
                    # This will be internally treated as a ForwardRef type. It will be resolved later
                    return model_name
            else:
                return dict[str, Any]
        else:
            raise NotImplementedError(f"Unsupported type: {param_type}")

    if not isinstance(param_def, ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType):
        # for inner obj
        param_def = ParamDef.from_param_obj(param_def)

    if isinstance(param_def, ParamDef.ParamGroup):
        type_annotation = generate_union_type(
            [resolve_type_annotation(param_name, p, _is_required=_is_required, _is_array=_is_array) for p in param_def]
        )
    else:
        if enum := param_def.get("enum"):
            type_annotation = generate_literal_type(*enum)
        elif isinstance(param_def, ParamDef.UnknownType):
            logger.warning(
                f"Param '{param_name}': Unable to locate a parameter type in the following parameter object. "
                f"Type '{Any}' will be applied:\n"
                f"{param_def.param_obj}"
            )
            type_annotation = Any
        else:
            type_annotation = resolve(param_def.type, param_format=param_def.format)

        # Add metadata
        if param_def.is_deprecated:
            type_annotation = annotate_type(type_annotation, "deprecated")
        if isinstance(param_def, ParamDef) and any(filter(None, list(asdict(param_def.constraint).values()))):
            type_annotation = annotate_type(type_annotation, param_def.constraint)

        if (
            _is_required is not True
            and not _is_array
            and not is_optional_type(type_annotation)
            and isinstance(param_def, ParamDef)
            and (_is_required is False or not param_def.is_required)
        ):
            # Optional parameter
            type_annotation = generate_optional_type(type_annotation)

    if num_optional_types := repr(type_annotation).count("Optional"):
        # Sanity check for Optional type. If it is annotated with `Optional`, we want it to appear as the origin type
        # only. If this check fails, it means the logic is broke somewhere
        if num_optional_types > 1:
            raise RuntimeError(f"{Optional} should not appear more than once: {type_annotation}")
        if type_annotation.__name__ != Optional.__name__:  # type: ignore[attr-defined]
            raise RuntimeError(f"{Optional} should be the outer most type: {type_annotation}")
    return type_annotation


def get_base_type(tp: Any, return_if_container_type: bool = False) -> Any | list[Any]:
    """Get the base type from the type annotation

    eg:
        Optional[str] -> str
        Optional[str | int] -> str | int
        Annotated[str, "metadata"] -> str
        Literal[1,2,3] -> Literal[1,2,3]
        list[str] -> str (list[str] if return_if_container_type=True)
        str | int -> str | int

        NOTE: This should also work with the combination of above

    :param tp: Type annotation
    :param return_if_container_type: Consider container type like list and tuple as the inner type
    """
    if origin_type := get_origin(tp):
        if origin_type not in [Optional, Union, UnionType, Annotated, Literal, list, dict]:
            raise RuntimeError(f"Found unexpected origin type in '{tp}': {origin_type}")

        if is_union_type(tp):
            args_without_nonetype = [x for x in get_args(tp) if x is not NoneType]
            return generate_union_type([get_base_type(x) for x in args_without_nonetype])
        elif origin_type is Annotated:
            return get_base_type(tp.__origin__)
        elif origin_type is list:
            if return_if_container_type:
                return tp
            else:
                return get_base_type(get_args(tp)[0])
    return tp


def replace_base_type(tp: Any, new_type: Any, replace_container_type: bool = False) -> Any:
    """Replace the base type of the type annotation to something else

    :param tp: The original type annotation
    :param new_type: A new type to replace the base type with
    :param replace_container_type: Treat container types like list and tuple as an base type

    >>> tp = Optional[Annotated[int, "metadata"]]
    >>> new_tp = replace_base_type(tp, str)
    >>> print(new_tp)
    typing.Optional[typing.Annotated[str, 'metadata']]
    """

    if origin_type := get_origin(tp):
        args = get_args(tp)
        if is_union_type(tp):
            if is_optional_type(tp):
                return generate_optional_type(replace_base_type(args[0], new_type))
            else:
                return replace_base_type(args, new_type)
        elif origin_type is Annotated:
            return annotate_type(replace_base_type(tp.__origin__, new_type), *tp.__metadata__)
        elif origin_type in [list, tuple]:
            if replace_container_type:
                return new_type
            else:
                return origin_type[replace_base_type(args, new_type)]
        else:
            return new_type
    else:
        return new_type


def is_type_of(param_type: str | Any, type_to_check: Any) -> bool:
    """Check if the specified type falls into the given parameter type

    eg. This will return True:
        - param_type=Annotated[list[Any]]
        - type_to_check=list

    :param tp: OpenAPI parameter type or python type annotation
    :param type_to_check: Python type
    """
    if isinstance(param_type, str):
        # OpenAPI param type
        if type_to_check is list:
            return param_type in LIST_PARAM_TYPES
        elif type_to_check is str:
            return param_type in STR_PARAM_TYPES
        elif type_to_check is bool:
            return param_type in BOOL_PARAM_TYPES
        elif type_to_check is int:
            return param_type in INT_PARAM_TYPES
        elif type_to_check is None:
            return param_type in NULL_PARAM_TYPES
        else:
            # Add if needed
            raise NotImplementedError
    elif origin_type := get_origin(param_type):
        if (origin_type is type_to_check) or (origin_type is Union and type_to_check in [Optional, Optional_]):
            return True
        elif origin_type is Annotated:
            return is_type_of(param_type.__origin__, type_to_check)
        elif is_union_type(param_type):
            return any([is_type_of(x, type_to_check) for x in get_args(param_type)])
    return param_type is type_to_check


def is_optional_type(tp: Any) -> bool:
    """Check if the type can be annotated with Optional

    :param tp: Type annotation
    """
    if is_union_type(tp) and NoneType in get_args(tp):
        return True
    else:
        origin_type = get_origin(tp)
        if origin_type in [list, dict, tuple]:
            return any([is_optional_type(m) for m in get_args(tp)])
        elif origin_type == Annotated:
            return is_optional_type(tp.__origin__)
        else:
            return False


def is_union_type(tp: Any) -> bool:
    """Check if the type annotation is a Union type

    :param tp: Type annotation
    """
    origin_type = get_origin(tp)
    return origin_type in [Union, UnionType]


def is_deprecated_param(tp: Any) -> bool:
    """Check if the parameter type is annotated with "deprecated" metadata

    :param tp: Type annotation
    """
    if is_union_type(tp):
        return any(is_deprecated_param(x) for x in get_args(tp))
    else:
        return get_origin(tp) is Annotated and "deprecated" in tp.__metadata__


def generate_union_type(type_annotations: Sequence[Any]) -> Any:
    """Convert multiple annotations to a Union type

    :param type_annotations: type annotations
    """
    return reduce(or_, type_annotations)


def generate_optional_type(tp: Any) -> Any:
    """Convert the type annotation to Optional[tp]"""
    if is_optional_type(tp):
        return tp
    else:
        return Optional[tp]  # noqa: UP007


def generate_literal_type(*args: Any, uncacheable: bool = True) -> _LiteralGenericAlias:
    """Generate a Literal type annotation using given args

    :param args: Literal args
    :param uncacheable: Make this Literal type uncacheable
    """
    if uncacheable:
        cacheable_args = tuple(arg.obj if isinstance(arg, UncacheableLiteralArg) else arg for arg in args)
        args = tuple(UncacheableLiteralArg(arg) for arg in dedup(*cacheable_args))
    return Literal[*args]


def annotate_type(tp: Any, *metadata: Any) -> Any:
    """Annotate the provided type with `Annotated[]` with the metadata. If the provided type is already annotated,
    we will just add metadata to it.

    :param tp: Type annotation
    :param metadata: Metadata to add to Annotated[]
    """
    if get_annotated_type(tp):
        return modify_annotated_metadata(tp, *metadata, action="add")

    if get_origin(tp) is Annotated:
        return modify_annotated_metadata(tp, *metadata, action="add")
    elif is_optional_type(tp):
        inner_type = generate_union_type([x for x in get_args(tp) if x is not NoneType])
        return generate_optional_type(annotate_type(inner_type, *metadata))
    else:
        return Annotated[tp, *metadata]


def modify_annotated_metadata(annotated_tp: Any, *metadata: Any, action: Literal["add", "replace", "remove"]) -> Any:
    """Modify metadata in the annotated type. If the given type is a union of multiple Annotated types, the same
    action will be performed on both.

    :param annotated_tp: Annotated type annotation
    :param metadata: Metadata to add or replace
    :param action:
        - add: Add new metadata to the existing ones
        - remove: Remove given metadata from the existing ones
        - replace: Replace existing metadata with new ones
    """
    if not is_type_of(annotated_tp, Annotated):
        raise ValueError(f"'{annotated_tp}' is not a valid annotated type with Annotated[]")
    if not metadata:
        raise ValueError("At least one metadata must be provided")
    if action not in ["add", "replace", "remove"]:
        raise ValueError(f"Invalid action: {action}")

    def modify_metadata(tp: Any) -> Any:
        if get_origin(tp) is Annotated:
            if action == "add":
                new_metadata = dedup(*tp.__metadata__, *metadata)
            elif action == "remove":
                new_metadata = tuple(x for x in tp.__metadata__ if x not in metadata)
                if not new_metadata:
                    raise ValueError("At least one metadata must exist after the action is performed")
            else:
                new_metadata = dedup(*metadata)
            return annotate_type(get_args(tp)[0], *new_metadata)
        else:
            if is_union_type(tp):
                return generate_union_type([modify_metadata(arg) for arg in get_args(tp)])
            else:
                return tp

    return modify_metadata(annotated_tp)


def get_annotated_type(tp: Any) -> _AnnotatedAlias | tuple[_AnnotatedAlias] | None:
    """Get annotated type definition(s)

    NOTE: If the type annotation is a union of multiple Annotated[] types, all annotated types will be returned

    :param tp: Type annotation
    """
    if is_union_type(tp):
        annotated_types = tuple(filter(None, [get_annotated_type(arg) for arg in get_args(tp)]))
        if annotated_types:
            if len(annotated_types) == 1:
                return annotated_types[0]
            else:
                return annotated_types
        return None
    else:
        if get_origin(tp) is Annotated:
            return tp


def merge_annotation_types(tp1: Any, tp2: Any) -> Any:
    """Merge type annotations

    :param tp1: annotated type1
    :param tp2: annotated type2

    Note: This is still experimental
    """

    def merge_args_per_origin(args: Sequence[Any]) -> tuple[Any, ...]:
        """Merge type annotations per its origiin type"""
        origin_type_order = {Literal: 1, Annotated: 2, Union: 3, UnionType: 4, list: 5, dict: 6, None: 10}
        args_per_origin: dict[Any, list[Any]] = {}
        for arg in args:
            args_per_origin.setdefault(get_origin(arg), []).append(arg)
        return tuple(
            reduce(
                merge_annotation_types,
                sorted(args_, key=lambda x: origin_type_order.get(get_origin(x), 99)),
            )
            for args_ in args_per_origin.values()
        )

    if isinstance(tp1, str):
        tp1 = ForwardRef(tp1)
    if isinstance(tp2, str):
        tp2 = ForwardRef(tp2)

    origin = get_origin(tp1)
    origin2 = get_origin(tp2)
    if origin or origin2:
        if origin == origin2:
            args1 = get_args(tp1)
            args2 = get_args(tp2)
            # stop using set here
            combined_args = dedup(*args1, *args2)
            if origin is Literal:
                return generate_literal_type(*combined_args)
            elif origin is Annotated:
                # If two Annotated types have different set of ParamAnnotationType objects in metadata, treat them as
                # different types as a union type. Otherwise merge them
                # TODO: revisit this part
                annotation_types1 = [x for x in tp1.__metadata__ if isinstance(x, ParamAnnotationType)]
                annotation_types2 = [x for x in tp2.__metadata__ if isinstance(x, ParamAnnotationType)]
                if (
                    annotation_types1
                    and annotation_types1
                    and (sorted(repr(x) for x in annotation_types1) == sorted(repr(y) for y in annotation_types2))
                ) or not (annotation_types1 or annotation_types2):
                    combined_type = merge_annotation_types(get_args(tp1)[0], get_args(tp2)[0])
                    combined_metadata = dedup(*tp1.__metadata__, *tp2.__metadata__)
                    return annotate_type(combined_type, *combined_metadata)
                else:
                    return generate_union_type([tp1, tp2])
            elif origin is dict:
                key_type, val_type = args1
                key_type2, val_type2 = args2
                if key_type == key_type2:
                    if val_type == val_type2:
                        return dict[key_type, val_type]  # type: ignore[valid-type]
                    else:
                        return dict[key_type, merge_annotation_types(val_type, val_type2)]  # type: ignore[valid-type]
                else:
                    if val_type == val_type2:
                        return dict[generate_union_type((key_type, key_type2)), val_type]
            elif origin is list:
                return list[generate_union_type(merge_args_per_origin(combined_args))]
            elif origin in [Union, UnionType]:
                return generate_union_type(merge_args_per_origin(combined_args))

        # TODO: Needs improvements to cover more cases
        if is_optional_type(tp1):
            return generate_union_type([merge_annotation_types(get_args(tp1)[0], tp2), NoneType])
        elif is_optional_type(tp2):
            return generate_union_type([merge_annotation_types(tp1, get_args(tp2)[0]), NoneType])

    return generate_union_type((tp1, tp2))


def or_(x: Any, y: Any) -> Any:
    """Customized version of operator.or_ that treats our dynamically created param model classes with the same
    name as duplicates

    eg. operator.or_ v.s our or_
    >>> import operator
    >>> from openapi_test_client.libraries.api.types import ParamModel
    >>> Model1 = type("MyModel", (ParamModel,), {})
    >>> Model2 = type("MyModel", (ParamModel,), {})
    >>> reduce(operator.or_, [Model1 | None, Model2])
    __main__.MyModel | None | __main__.MyModel
    >>> reduce(or_, [Model1 | None, Model2])
    __main__.MyModel | None
    """
    if (
        param_model_util.is_param_model(x)
        and param_model_util.is_param_model(y)
        and param_model_util.get_param_model_name(x) == param_model_util.get_param_model_name(y)
    ):
        return x
    else:
        is_x_union = is_union_type(x)
        is_y_union = is_union_type(y)
        if is_x_union:
            if is_y_union:
                return reduce(or_, (*get_args(x), *get_args(y)))
            elif param_model_util.is_param_model(y):
                param_model_names_in_x = [
                    param_model_util.get_param_model_name(x) for x in get_args(x) if param_model_util.is_param_model(x)
                ]
                if param_model_util.get_param_model_name(y) in param_model_names_in_x:
                    return x
        elif is_y_union:
            return reduce(or_, (x, *get_args(y)))

    return x | y
