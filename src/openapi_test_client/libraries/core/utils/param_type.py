from __future__ import annotations

import inspect
from functools import reduce
from operator import or_ as _or_
from types import NoneType, UnionType
from typing import TYPE_CHECKING, Annotated, Any, ForwardRef, Literal, TypeVar, Union, get_args, get_origin

from common_libs.utils import dedup

from ..types import ParamAnnotationType, Query

if TYPE_CHECKING:
    from typing import _AnnotatedAlias  # type: ignore[attr-defined]


def is_type_of(param_type: Any, type_to_check: Any) -> bool:
    """Check if the specified type falls into the given parameter type

    eg. This will return True:
        - param_type=Annotated[list[Any]]
        - type_to_check=list

    :param param_type: Python type annotation
    :param type_to_check: Python type
    """
    if origin_type := get_origin(param_type):
        if origin_type is type_to_check:
            return True
        elif origin_type is Annotated:
            return is_type_of(param_type.__origin__, type_to_check)
        elif origin_type in (Union, UnionType):
            # Special case: type_to_check is an Optional alias (e.g. T | None TypeAlias) — check
            # if param_type is nullable rather than recursing into its union args
            if get_origin(type_to_check) in (Union, UnionType) and any(
                isinstance(a, TypeVar) for a in get_args(type_to_check)
            ):
                return NoneType in get_args(param_type)
            return any([is_type_of(x, type_to_check) for x in get_args(param_type)])
    return param_type is type_to_check


def matches_type(value: Any, tp: Any) -> bool:
    """Check if the value conforms to the provided type annotation

    :param value: Any value
    :param tp: Type annotation to check the value against
    """
    if tp is Any:
        return True
    if isinstance(tp, (str, ForwardRef)):
        # Unresolvable annotation (e.g. from __future__ import annotations with a local-variable
        # reference that get_type_hints() couldn't evaluate). isinstance() would raise TypeError.
        return False
    if value is None:
        return type(None) in get_args(tp)

    # Union / Optional
    if get_origin(tp) in (Union, UnionType):
        return any(matches_type(value, arg) for arg in get_args(tp))

    origin = get_origin(tp)
    if origin is Annotated:
        base, *_ = get_args(tp)
        if not matches_type(value, base):
            return False
        return True
    elif origin is Literal:
        return value in get_args(tp)
    elif origin is list:
        if not isinstance(value, list):
            return False
        (elem_type,) = get_args(tp)
        return all(matches_type(v, elem_type) for v in value)
    elif origin is dict:
        if not isinstance(value, dict):
            return False
        k_type, v_type = get_args(tp)
        return all(matches_type(k, k_type) for k in value.keys()) and all(
            matches_type(v, v_type) for v in value.values()
        )
    # TODO: Add more if needed

    return isinstance(value, tp)


def is_deprecated_param(tp: Any) -> bool:
    """Check if the parameter type is annotated with "deprecated" metadata

    :param tp: Type annotation
    """
    if get_origin(tp) in (Union, UnionType):
        return any(is_deprecated_param(x) for x in get_args(tp))
    else:
        return get_origin(tp) is Annotated and "deprecated" in tp.__metadata__


def is_query_param(tp: Any) -> bool:
    """Check if the parameter type is annotated to be sent as a URL query string.

    Recognizes three equivalent forms:
    - ``Annotated[T, Query()]``  — canonical instance
    - ``Annotated[T, Query]``    — bare class (ergonomic shortcut)
    - ``Annotated[T, "query"]``  — legacy string (kept for back-compat)

    :param tp: Type annotation
    """
    if get_origin(tp) in (Union, UnionType):
        return any(is_query_param(x) for x in get_args(tp))
    if get_origin(tp) is not Annotated:
        return False
    metadata = tp.__metadata__
    return "query" in metadata or any(isinstance(m, Query) or m is Query for m in metadata)


def annotate_type(tp: Any, *metadata: Any) -> Any:
    """Annotate the provided type with `Annotated[]` with the metadata. If the provided type is already annotated,
    we will just add metadata to it.

    :param tp: Type annotation
    :param metadata: Metadata to add to Annotated[]
    """
    origin = get_origin(tp)
    if origin is Annotated:
        new_metadata = dedup(*tp.__metadata__, *metadata)
        return origin[get_args(tp)[0], *new_metadata]
    elif origin in (Union, UnionType) and NoneType in get_args(tp):
        inner_args = [x for x in get_args(tp) if x is not NoneType]
        inner_type = reduce(_or_, inner_args) if len(inner_args) > 1 else inner_args[0]
        return annotate_type(inner_type, *metadata) | None
    else:
        return Annotated[tp, *metadata]


def get_annotated_type(
    tp: Any, metadata_filter: str | type[ParamAnnotationType] | list[str | type[ParamAnnotationType]] | None = None
) -> _AnnotatedAlias | tuple[_AnnotatedAlias] | None:
    """Get annotated type definition(s) from the provided type annotation

    NOTE: If the type annotation is a union of multiple Annotated[] types, all annotated types will be returned

    :param tp: Type annotation
    :param metadata_filter: Filter by metadata
    """
    if metadata_filter and not isinstance(metadata_filter, list):
        metadata_filter = [metadata_filter]

    if get_origin(tp) in (Union, UnionType):
        annotated_types = tuple(
            filter(None, [get_annotated_type(arg, metadata_filter=metadata_filter) for arg in get_args(tp)])
        )
        if annotated_types:
            if len(annotated_types) == 1:
                return annotated_types[0]
            else:
                return annotated_types
        return None
    else:
        origin = get_origin(tp)
        if origin is Annotated:
            if metadata_filter:
                metadata = tp.__metadata__
                for x in metadata_filter:
                    if (isinstance(x, str) and x in metadata) or (
                        inspect.isclass(x)
                        and issubclass(x, ParamAnnotationType)
                        and any(isinstance(m, x) or m is x for m in metadata)
                    ):
                        return tp
                return None
            return tp
        elif origin is list:
            return get_annotated_type(get_args(tp)[0], metadata_filter=metadata_filter)
        # TODO: Add more?
