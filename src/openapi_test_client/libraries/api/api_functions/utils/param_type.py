import inspect
from collections.abc import Sequence
from dataclasses import asdict
from functools import reduce
from operator import or_
from types import NoneType, UnionType
from typing import _AnnotatedAlias  # noqa
from typing import Annotated, Any, Literal, Optional, Union, get_args, get_origin

from common_libs.logging import get_logger

import openapi_test_client.libraries.api.api_functions.utils.param_model as param_model_util
from openapi_test_client.libraries.api.types import Alias, Constraint, Format, ParamDef
from openapi_test_client.libraries.common.constants import BACKSLASH

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
    elif get_origin(tp) is Annotated:
        orig_type = get_type_annotation_as_str(tp.__origin__)
        metadata_types = ", ".join(get_type_annotation_as_str(m) for m in tp.__metadata__)
        return f"{Annotated.__name__}[{orig_type}, {metadata_types}]"
    elif is_union_type(tp):
        args = get_args(tp)
        if NoneType in args:
            inner_types = [x for x in args if x is not NoneType]
            if len(inner_types) == 1:
                return f"{Optional.__name__}[{get_type_annotation_as_str(inner_types[0])}]"
            else:
                inner_types_union = " | ".join(get_type_annotation_as_str(x) for x in inner_types)
                # Note: This is actually Union[tp1, ..., None] in Python, but we annotate this as
                # Optional[tp1 | ...] in code
                return f"{Optional.__name__}[{inner_types_union}]"
        else:
            return " | ".join(get_type_annotation_as_str(x) for x in args)
    elif get_origin(tp) in [list, dict, tuple]:
        inner_types = ", ".join(get_type_annotation_as_str(t) for t in get_args(tp))
        return f"{tp.__origin__.__name__}[{inner_types}]"
    elif get_origin(tp) is Literal:
        return repr(tp).replace("typing.", "")
    elif isinstance(tp, Alias | Format):
        return f"{type(tp).__name__}({repr(tp.value)})"
    elif isinstance(tp, Constraint):
        const = ", ".join(
            f'{k}={("r" + repr(v).replace(BACKSLASH * 2, BACKSLASH) if k == "pattern" else repr(v))}'
            for k, v in asdict(tp).items()
            if v is not None
        )
        return f"{type(tp).__name__}({const})"
    elif tp is NoneType:
        return "None"
    else:
        if inspect.isclass(tp):
            return tp.__name__
        else:
            return type(tp).__name__


def resolve_type_annotation(
    param_name: str,
    param_def: ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType,
    _is_required: bool | None = None,
    _is_array: bool = False,
) -> Any:
    """Resolve type annotation for the given parameter definition

    :param param_name: Parameter name
    :param param_def: Param def
    :param _is_required: Force this parameter required (even if API specs say not required)
    :param _is_array: Indicates that this parameter is a list type
    """

    def resolve(param_type: str, param_format: str = None):
        """Resolve type annotation

        NOTE: Some OpenAPI spec use a wrong param type value (eg. string v.s. str).
              We handle these scenarios accordingly
        """
        if param_type in STR_PARAM_TYPES:
            if param_format:
                return generate_annotated_type(str, Format(param_format))
            else:
                return str
        elif param_type in INT_PARAM_TYPES:
            if param_type == "number" and param_format == "float":
                return float
            elif param_format:
                return generate_annotated_type(int, Format(param_format))
            else:
                return int
        elif param_type in BOOL_PARAM_TYPES:
            return bool
        elif param_type in NULL_PARAM_TYPES:
            return None
        elif param_type in LIST_PARAM_TYPES:
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
            if "properties" in param_def:
                # Param model
                model_name = param_model_util.generate_model_name(param_name, list if _is_array else Any)
                return param_model_util.create_model_from_param_def(model_name, param_def)
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
            # NOTE: This is not a valid way to use Literal but the actual type annotation we will see in the generated
            # code will be valid. So ignoring the warning here.
            type_annotation = Literal[*enum]  # type: ignore
        elif isinstance(param_def, ParamDef.UnknownType):
            logger.exception(
                f"Unable to locate a parameter type for parameter '{param_name}'. Type '{Any}' will be applied.\n"
                f"Failed parameter object:\n{param_def.param_obj}"
            )
            type_annotation = Any
        else:
            type_annotation = resolve(param_def.type, param_format=param_def.format)

        # Add metadata
        if param_def.is_deprecated:
            type_annotation = generate_annotated_type(type_annotation, "deprecated")
        if isinstance(param_def, ParamDef) and any(filter(None, list(asdict(param_def.constraint).values()))):
            type_annotation = generate_annotated_type(type_annotation, param_def.constraint)

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
        if type_annotation.__name__ != Optional.__name__:
            raise RuntimeError(f"{Optional} should be the outer most type: {type_annotation}")
    return type_annotation


def get_inner_type(tp: Any, return_if_container_type: bool = False) -> Any | tuple[Any] | list[Any]:
    """Get the inner type (=actual type) from the type annotation

    eg:
        Optional[str] -> str
        Annotated[str, "metadata"] -> str
        Literal[1,2,3] -> Literal[1,2,3]
        list[str] -> str (list[str] if return_if_container_type=True)
        str | int -> (str, int)

        NOTE: This should also work with the combination of above

    :param tp: Type annotation
    :param return_if_container_type: Consider container type like list and tuple as the inner type
    """
    if origin_type := get_origin(tp):
        args = get_args(tp)
        if is_union_type(tp):
            if is_optional_type(tp):
                return get_inner_type(args[0])
            else:
                return args
        elif origin_type is Annotated:
            return get_inner_type(tp.__origin__)
        elif origin_type in [list, tuple]:
            if return_if_container_type:
                return tp
            else:
                if origin_type is list:
                    return get_inner_type(args[0])
                else:
                    return get_inner_type(args)
        else:
            return tp
    else:
        return tp


def replace_inner_type(tp: Any, new_type: Any, replace_container_type: bool = False) -> Any:
    """Replace an inner type of in the type annotation to something else

    :param tp: The original type annotation
    :param new_type: A new type to replace the inner type with
    :param replace_container_type: Treat container types like list and tuple as an inner type

    >>> tp = Optional[Annotated[int, "metadata"]]
    >>> new_tp = replace_inner_type(tp, str)
    >>> print(new_tp)
    typing.Optional[typing.Annotated[str, 'metadata']]
    """

    if origin_type := get_origin(tp):
        args = get_args(tp)
        if is_union_type(tp):
            if is_optional_type(tp):
                return Optional[replace_inner_type(args[0], new_type)]  # noqa: UP007
            else:
                return replace_inner_type(args, new_type)
        elif origin_type is Annotated:
            return Annotated[replace_inner_type(tp.__origin__, new_type), *tp.__metadata__]
        elif origin_type in [list, tuple]:
            if replace_container_type:
                return new_type
            else:
                return origin_type[replace_inner_type(args, new_type)]
        else:
            return new_type
    else:
        return new_type


def is_type_of(tp: str | Any, type_to_check: Any) -> bool:
    """Check if the given param type is same as the specified type to check

    eg. This will return True:
        - param_type=Annotated[list[Any]]
        - type_to_check=list

    :param tp: OpenAPI parameter type or python type annotation
    :param type_to_check: Python type
    """
    if isinstance(tp, str):
        # OpenAPI param type
        if type_to_check is list:
            return tp in LIST_PARAM_TYPES
        elif type_to_check is str:
            return tp in STR_PARAM_TYPES
        elif type_to_check is bool:
            return tp in BOOL_PARAM_TYPES
        elif type_to_check is int:
            return tp in LIST_PARAM_TYPES
        elif type_to_check is None:
            return tp in NULL_PARAM_TYPES
        else:
            # Add if needed
            raise NotImplementedError
    elif origin_type := get_origin(tp):
        if origin_type is type_to_check:
            return True
        elif origin_type is Annotated:
            return is_type_of(tp.__origin__, type_to_check)
        elif is_union_type(tp):
            return any([is_type_of(x, type_to_check) for x in get_args(tp)])
    else:
        return tp is type_to_check


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
    if is_optional_type(tp):
        return any(is_deprecated_param(x) for x in get_args(tp))
    else:
        return get_origin(tp) is Annotated and "deprecated" in tp.__metadata__


def generate_union_type(type_annotations: Sequence[Any]) -> Any:
    """Convert multiple annotations to a Union type

    :param type_annotations: type annotations
    """
    if len(set(repr(x) for x in type_annotations)) == 1:
        # All annotations are the same
        type_annotation = type_annotations[0]
    else:
        type_annotation = reduce(or_, type_annotations)
    return type_annotation


def generate_optional_type(tp: Any) -> Any:
    """Convert the type annotation to Optional[tp]

    Wrap the type with `Optional[]`, but using `Union` with None instead as there seems to be a cache issue
    where `Optional[Literal['val1', 'val2']]` with change the order of Literal parameters due to the cache.

    eg. The issue seen in Python 3.11
    >>> t1 = Literal["foo", "bar"]
    >>> Optional[t1]
    typing.Optional[typing.Literal['foo', 'bar']]
    >>> t2 = Literal["bar", "foo"]
    >>> Optional[t2]
    typing.Optional[typing.Literal['foo', 'bar']]  <--- HERE
    """
    if is_optional_type(tp):
        return tp
    else:
        return Union[tp, None]  # noqa: UP007


def generate_annotated_type(tp: Any, metadata: Any):
    """Add `Annotated` type to the type annotation with the metadata

    :param tp: Type annotation
    """
    if is_optional_type(tp):
        inner_type = get_args(tp)[0]
        return Optional[Annotated[inner_type, metadata]]  # noqa: UP007
    else:
        return Annotated[tp, metadata]


def get_annotated_type(tp: Any) -> _AnnotatedAlias | None:
    """Get annotated type definition

    :param tp: Type annotation
    """
    if is_optional_type(tp):
        inner_type = get_args(tp)[0]
        return get_annotated_type(inner_type)
    else:
        if get_origin(tp) is Annotated:
            return tp
