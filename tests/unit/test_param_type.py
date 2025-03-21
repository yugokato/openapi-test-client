import re
from dataclasses import dataclass, make_dataclass
from types import NoneType
from typing import Annotated, Any, ForwardRef, Literal, get_args, get_origin

import pytest

import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
from openapi_test_client.libraries.api.types import (
    Alias,
    Constraint,
    Format,
    Optional,
    ParamModel,
    UncacheableLiteralArg,
    Unset,
)


class MyClass: ...


@dataclass
class MyParamModel(ParamModel):
    param1: str = Unset
    param2: str = Unset


MyParamModel2 = make_dataclass(MyParamModel.__name__, [("foo", str, Unset)], bases=(ParamModel,))
MyParamModel3 = make_dataclass(MyParamModel.__name__, [("bar", int, Unset)], bases=(ParamModel,))


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize("is_optional", [False, True])
@pytest.mark.parametrize(
    ("tp", "expected_tp_str"),
    [
        (None, "None"),
        (NoneType, "None"),
        (Any, "Any"),
        (str, "str"),
        (int, "int"),
        (bool, "bool"),
        (list, "list"),
        (dict, "dict"),
        (dict[str, Any], "dict[str, Any]"),
        (Literal[None], "Literal[None]"),
        (Literal[UncacheableLiteralArg(None)], "Literal[None]"),
        (Literal["1", "2"], "Literal['1', '2']"),
        (Literal[UncacheableLiteralArg("1"), UncacheableLiteralArg("2")], "Literal['1', '2']"),
        (MyClass, MyClass.__name__),
        (MyParamModel, MyParamModel.__name__),
        (ForwardRef(MyParamModel.__name__), MyParamModel.__name__),
        # Union/Optional
        (str | int, "str | int"),
        (dict[str, Any] | MyParamModel, f"dict[str, Any] | {MyParamModel.__name__}"),
        (int | None, "Optional[int]"),
        (int | None | MyParamModel, f"Optional[int | {MyParamModel.__name__}]"),
        # Annotated
        (Annotated[str, "meta"], "Annotated[str, 'meta']"),
        (
            Annotated[str, "meta1", "meta2", Format(value="uuid"), Alias("foo"), Constraint(min=1)],
            "Annotated[str, 'meta1', 'meta2', Format('uuid'), Alias('foo'), Constraint(min=1)]",
        ),
        (
            Annotated[str, "meta", Constraint(pattern=r"^[A-Z]+$")],
            "Annotated[str, 'meta', Constraint(pattern=r'^[A-Z]+$')]",
        ),
        (Annotated[str | int, "meta"], "Annotated[str | int, 'meta']"),
    ],
)
def test_get_type_annotation_as_str(tp: Any, expected_tp_str: str, is_optional: bool, as_list: bool) -> None:
    """Verify that a string version of type annotation can be generated from various annotated types"""
    if (tp in [NoneType, None] or isinstance(tp, str)) and (is_optional or as_list):
        pytest.skip("Not applicable")

    if as_list:
        if get_origin(tp) is Annotated:
            inner_type = get_args(tp)[0]
            tp = Annotated[list[inner_type], *tp.__metadata__]  # type: ignore[valid-type]
            expected_tp_str = re.sub(r"Annotated\[([^,]+)", r"Annotated[list[\1]", expected_tp_str)
        else:
            tp = list[tp]
            expected_tp_str = f"list[{expected_tp_str}]"
    if is_optional and not expected_tp_str.startswith("Optional["):
        tp = Optional[tp]
        expected_tp_str = f"Optional[{expected_tp_str}]"

    assert param_type_util.get_type_annotation_as_str(tp) == expected_tp_str


@pytest.mark.parametrize(
    ("tp", "expected_type"),
    [
        (None, None),
        (NoneType, NoneType),
        (Any, Any),
        (str, str),
        (int, int),
        (bool, bool),
        (dict, dict),
        (dict[str, Any], dict[str, Any]),
        (list, list),
        (Literal[None], Literal[None]),
        (Literal["1", "2"], Literal["1", "2"]),
        (MyClass, MyClass),
        (MyParamModel, MyParamModel),
        (ForwardRef(MyParamModel.__name__), ForwardRef(MyParamModel.__name__)),
        (str | int, str | int),
        (str | None, str),
        (str | int | None, str | int),
        (Annotated[str, Constraint(min_len=5)] | Annotated[int, Constraint(min=5)], str | int),
        (list[str], str),
        (list[dict[str, Any]], dict[str, Any]),
        (Annotated[str, "meta"], str),
        (Optional[str], str),
        (Optional[str | int], str | int),
        (Optional[MyClass], MyClass),
        (Optional[MyParamModel], MyParamModel),
        (Optional[ForwardRef(MyParamModel.__name__)], ForwardRef(MyParamModel.__name__)),
        (Optional[list[str]], str),
        (Optional[Annotated[str, "meta"]], str),
        (Optional[Annotated[str, "meta"] | int], str | int),
        (Optional[Literal["1", "2"]], Literal["1", "2"]),
        (Optional[Annotated[MyParamModel, "meta"]], MyParamModel),
        (Optional[Annotated[ForwardRef(MyParamModel.__name__), "meta"]], ForwardRef(MyParamModel.__name__)),
        (Optional[Annotated[list[str], "meta"]], str),
    ],
)
def test_get_base_type(tp: Any, expected_type: Any) -> None:
    """Verify that the base type can be identified from various type annotations"""
    assert param_type_util.get_base_type(tp) == expected_type


@pytest.mark.parametrize(
    ("tp", "replace_with", "expected_type"),
    [
        (str, str, str),
        (str, int, int),
        (str, Literal[1, 2], Literal[1, 2]),
        (Literal[None], str, str),
        (Literal[1, 2], str, str),
        (Literal[1, 2], Literal[2, 3], Literal[2, 3]),
        (ForwardRef(MyClass.__name__), str, str),
        (str | int, bool, bool),
        (list[str], int, list[int]),
        (Optional[str], int, Optional[int]),
        (Optional[str | int], bool, Optional[bool]),
        (Optional[dict[str, Any]], MyParamModel, Optional[MyParamModel]),
        (Optional[ForwardRef(MyParamModel.__name__)], str, Optional[str]),
        (Annotated[str, "meta", Constraint(min=1)], int, Annotated[int, "meta", Constraint(min=1)]),
        (Annotated[str | int, "meta"], bool, Annotated[bool, "meta"]),
        (Optional[Annotated[str, "meta"]], int, Optional[Annotated[int, "meta"]]),
        (Optional[Annotated[dict[str, Any], "meta"]], MyParamModel, Optional[Annotated[MyParamModel, "meta"]]),
        (Optional[Annotated[ForwardRef(MyParamModel.__name__), "meta"]], str, Optional[Annotated[str, "meta"]]),
    ],
)
def test_replace_baser_type(tp: Any, replace_with: Any, expected_type: Any) -> None:
    """Verify that the base type of the type annotation can be replaced with another type"""
    assert param_type_util.replace_base_type(tp, replace_with) == expected_type


@pytest.mark.parametrize(
    ("param_type", "type_to_check", "is_type_of"),
    [
        ("str", str, True),
        ("string", str, True),
        (str, str, True),
        (Optional[str], str, True),
        (Annotated[str, "meta"], str, True),
        (Optional[Annotated[str, "meta"]], str, True),
        ("integer", int, True),
        ("int", int, True),
        ("int64", int, True),
        ("number", int, True),
        (int, int, True),
        (Optional[int], int, True),
        (Annotated[int, "meta"], int, True),
        (Optional[Annotated[int, "meta"]], int, True),
        ("bool", bool, True),
        ("boolean", bool, True),
        (bool, bool, True),
        (Optional[bool], bool, True),
        (Annotated[bool, "meta"], bool, True),
        (Optional[Annotated[bool, "meta"]], bool, True),
        ("array", list, True),
        (list, list, True),
        (list[str], list, True),
        (Optional[list[str]], list, True),
        (Annotated[list[str], "meta"], list, True),
        (Optional[Annotated[list[str], "meta"]], list, True),
        (str, int, False),
        (list[str], str, False),
        (Annotated[list[str], "meta"], str, False),
        (Optional[Annotated[list[str], "meta"]], str, False),
        (Optional[Annotated[Literal[1], "meta"]], Optional, True),
        (Optional[Annotated[Literal[1], "meta"]], Annotated, True),
        (Optional[Annotated[Literal[1], "meta"]], Literal, True),
    ],
)
def test_is_type_of(param_type: Any, type_to_check: Any, is_type_of: bool) -> None:
    """Verify that we can check if a specific Python type falls into an OpenAPI parameter type or a Python type"""
    assert param_type_util.is_type_of(param_type, type_to_check) is is_type_of


@pytest.mark.parametrize(
    ("tp", "is_optional_type"),
    [
        (None, False),
        (str, False),
        (Literal[None], False),
        (str | int, False),
        (str | None, True),
        (Optional[str], True),
        (str | Optional[str], True),
        (Annotated[str | None, "meta"], True),
        (Optional[Annotated[str, "meta"]], True),
        (Optional[Annotated[str | int, "meta"]], True),
    ],
)
def test_is_optional_type(tp: Any, is_optional_type: bool) -> None:
    """Verify that we can check whether a given type annotation can be used for an optional parameter type or not

    Note: The definiton of optional here means either Optional[] or a union type with None as one of the args
    """
    assert param_type_util.is_optional_type(tp) is is_optional_type


@pytest.mark.parametrize("exclude_optional", [False, True])
@pytest.mark.parametrize(
    ("tp", "is_union_type"),
    [
        (None, False),
        (str, False),
        (Literal[None], False),
        (str | int, True),
        (str | None, True),
        (Optional[str], True),
        (str | Optional[str], True),
        (Annotated[str | None, "meta"], False),
        (Optional[Annotated[str, "meta"]], True),
        (Optional[Annotated[str | int, "meta"]], True),
    ],
)
def test_is_union_type(tp: Any, is_union_type: bool, exclude_optional: bool) -> None:
    """Verify that we can check whether a given type annotation itself is a union type or not

    Note: Optional[] is also considered as union
    """
    if exclude_optional:
        is_union = is_union_type and NoneType not in get_args(tp)
    else:
        is_union = is_union_type
    assert param_type_util.is_union_type(tp, exclude_optional=exclude_optional) is is_union


@pytest.mark.parametrize(
    ("tp", "is_deprecated_param"),
    [
        (str, False),
        (int | Annotated[str, "meta"], False),
        (Annotated[str, "meta"], False),
        (Annotated[str, "meta", "deprecated"], True),
        (Annotated[str, "meta", "deprecated"], True),
        (int | Annotated[str, "meta", "deprecated"], True),
        (Optional[Annotated[str, "meta", "deprecated"]], True),
        (int | Optional[Annotated[str, "meta", "deprecated"]], True),
        (Optional[int] | Annotated[str, "meta", "deprecated"], True),
    ],
)
def test_is_deprecated_param(tp: Any, is_deprecated_param: bool) -> None:
    """Verify that we can check whether a given type annotation has `Annotated[]` with "deprecated" in the metadata"""
    assert param_type_util.is_deprecated_param(tp) is is_deprecated_param


@pytest.mark.parametrize(
    ("types", "expected_type"),
    [
        ([None], None),
        ([str], str),
        ([str, str], str),
        ([str, int], str | int),
        ([str, int, None], str | int | None),
        ([str, int, None, str, int, None], str | int | None),
        ([MyParamModel, MyParamModel, dict[str, Any]], MyParamModel | dict[str, Any]),
        (
            [MyParamModel, MyParamModel2, dict[str, Any]],
            MyParamModel | dict[str, Any],
        ),
    ],
)
def test_generate_union_type(types: list[Any], expected_type: Any) -> None:
    """Verify that a union type annotation can be generated from multiple type annotations"""
    assert param_type_util.generate_union_type(types) == expected_type


@pytest.mark.parametrize(
    ("tp", "expected_type"),
    [
        (str, Optional[str]),
        (str | int, Optional[str | int]),
        (str | None, Optional[str]),
        (str | int | None, Optional[str | int]),
        (list[str], Optional[list[str]]),
        (Annotated[str, "meta"], Optional[Annotated[str, "meta"]]),
        (Optional[str], Optional[str]),
        (Optional[Annotated[str, "meta"]], Optional[Annotated[str, "meta"]]),
    ],
)
def test_generate_optional_type(tp: Any, expected_type: Any) -> None:
    """Verify that a type annotation can be converted to an optional type with Optional[]"""
    assert param_type_util.generate_optional_type(tp) == expected_type


@pytest.mark.parametrize("uncacheable", [True, False])
def test_generate_literal_type(uncacheable: bool) -> None:
    """Verify that a literal type annotation can be generated with/without the typing module's caching mechanism"""
    args1 = ["1", "2", "2", "3"]
    args2 = ["3", "2", "1", "2"]
    tp1 = param_type_util.generate_literal_type(*args1, uncacheable=uncacheable)
    tp2 = param_type_util.generate_literal_type(*args2, uncacheable=uncacheable)
    if uncacheable:
        assert tp1 != tp2
        assert repr(Optional[tp1]) == "typing.Optional[typing.Literal['1', '2', '3']]"
        assert repr(Optional[tp2]) == "typing.Optional[typing.Literal['3', '2', '1']]"
    else:
        # NOTE: This is the default behavior of typing.Literal
        assert Literal[*args1] == tp1 == tp2
        assert repr(Optional[tp1]) == "typing.Optional[typing.Literal['1', '2', '3']]"
        assert repr(Optional[tp2]) == "typing.Optional[typing.Literal['1', '2', '3']]"


@pytest.mark.parametrize(
    ("tp", "metadata", "expected_type"),
    [
        (str, ["meta"], Annotated[str, "meta"]),
        (
            str,
            ["meta", Format("uuid"), Alias("foo"), Constraint(max=10)],
            Annotated[str, "meta", Format("uuid"), Alias("foo"), Constraint(max=10)],
        ),
        (str | int, ["meta"], Annotated[str | int, "meta"]),
        (Optional[str], ["meta"], Optional[Annotated[str, "meta"]]),
        (Optional[MyParamModel], ["meta"], Optional[Annotated[MyParamModel, "meta"]]),
        (
            Optional[ForwardRef(MyParamModel.__name__)],
            ["meta"],
            Optional[Annotated[ForwardRef(MyParamModel.__name__), "meta"]],
        ),
        (Optional[str | int], ["meta"], Optional[Annotated[str | int, "meta"]]),
    ],
)
def test_annotate_type(tp: Any, metadata: list[Any], expected_type: Any) -> None:
    """Verify that a type annotation can be converted to an annotated type with metadata"""
    assert param_type_util.annotate_type(tp, *metadata) == expected_type


@pytest.mark.parametrize(
    ("tp", "metadata", "expected_type"),
    [
        (Annotated[str, "meta1"], ["meta2"], Annotated[str, "meta1", "meta2"]),
        (Annotated[str, "meta1", "meta2"], ["meta2", "meta3"], Annotated[str, "meta1", "meta2", "meta3"]),
        (Optional[Annotated[str, "meta1"]], ["meta2"], Optional[Annotated[str, "meta1", "meta2"]]),
        (Optional[Annotated[str | int, "meta1"]], ["meta2"], Optional[Annotated[str | int, "meta1", "meta2"]]),
        (int | Annotated[str, "meta1"], ["meta2"], int | Annotated[str, "meta1", "meta2"]),
        (Annotated[str, "meta1"] | int, ["meta2"], Annotated[str, "meta1", "meta2"] | int),
        (Optional[int] | Annotated[str, "meta1"], ["meta2"], Optional[int] | Annotated[str, "meta1", "meta2"]),
        (int | Optional[Annotated[str, "meta1"]], ["meta2"], int | Optional[Annotated[str, "meta1", "meta2"]]),
        (
            Annotated[int, "meta1"] | Annotated[str, "meta1", "meta2"],
            ["meta3"],
            Annotated[int, "meta1", "meta3"] | Annotated[str, "meta1", "meta2", "meta3"],
        ),
    ],
)
def test_add_annotated_metadata(tp: Any, metadata: list[Any], expected_type: Any) -> None:
    """Verify that new metadata can be added to existing ones in the annotated type"""
    assert param_type_util.modify_annotated_metadata(tp, *metadata, action="add") == expected_type


@pytest.mark.parametrize(
    ("tp", "metadata", "expected_type"),
    [
        (Annotated[str, "meta1", "meta2"], ["meta2"], Annotated[str, "meta1"]),
        (Annotated[str, "meta1", "meta2"], ["meta2", "meta3"], Annotated[str, "meta1"]),
        (Optional[Annotated[str, "meta1", "meta2"]], ["meta2"], Optional[Annotated[str, "meta1"]]),
        (Optional[Annotated[str | int, "meta1", "meta2"]], ["meta2"], Optional[Annotated[str | int, "meta1"]]),
        (int | Annotated[str, "meta1", "meta2"], ["meta2"], int | Annotated[str, "meta1"]),
        (Annotated[str, "meta1", "meta2"] | int, ["meta2"], Annotated[str, "meta1"] | int),
        (Optional[int] | Annotated[str, "meta1", "meta2"], ["meta2"], Optional[int] | Annotated[str, "meta1"]),
        (int | Optional[Annotated[str, "meta1", "meta2"]], ["meta2"], int | Optional[Annotated[str, "meta1"]]),
        (
            Annotated[int, "meta1", "meta2"] | Annotated[str, "meta1", "meta2", "meta3"],
            ["meta2"],
            Annotated[int, "meta1"] | Annotated[str, "meta1", "meta3"],
        ),
    ],
)
def test_remove_annotated_metadata(tp: Any, metadata: list[Any], expected_type: Any) -> None:
    """Verify that one or more metadata in the annotated type can be removed"""
    assert param_type_util.modify_annotated_metadata(tp, *metadata, action="remove") == expected_type


@pytest.mark.parametrize(
    ("tp", "metadata", "expected_type"),
    [
        (Annotated[str, "meta1", "meta2"], ["meta3"], Annotated[str, "meta3"]),
        (Annotated[str, "meta1", "meta2"], ["meta2", "meta3"], Annotated[str, "meta2", "meta3"]),
        (Optional[Annotated[str, "meta1", "meta2"]], ["meta2"], Optional[Annotated[str, "meta2"]]),
        (Optional[Annotated[str | int, "meta1", "meta2"]], ["meta2"], Optional[Annotated[str | int, "meta2"]]),
        (int | Annotated[str, "meta1", "meta2"], ["meta2"], int | Annotated[str, "meta2"]),
        (Annotated[str, "meta1", "meta2"] | int, ["meta2"], Annotated[str, "meta2"] | int),
        (Optional[int] | Annotated[str, "meta1", "meta2"], ["meta2"], Optional[int] | Annotated[str, "meta2"]),
        (int | Optional[Annotated[str, "meta1", "meta2"]], ["meta2"], int | Optional[Annotated[str, "meta2"]]),
        (
            Annotated[int, "meta1", "meta2"] | Annotated[str, "meta1", "meta2", "meta3"],
            ["meta2"],
            Annotated[int, "meta2"] | Annotated[str, "meta2"],
        ),
    ],
)
def test_replace_annotated_metadata(tp: Any, metadata: list[Any], expected_type: Any) -> None:
    """Verify that metadata in the annotated type can be replaced with new value(s)"""
    assert param_type_util.modify_annotated_metadata(tp, *metadata, action="replace") == expected_type


@pytest.mark.parametrize(
    ("tp", "annotated_type"),
    [
        (str, None),
        (Optional[str], None),
        (str | int, None),
        (list[str], None),
        (Annotated[str, "meta"], Annotated[str, "meta"]),
        (int | Annotated[str, "meta"], Annotated[str, "meta"]),
        (Annotated[str, "meta"] | int, Annotated[str, "meta"]),
        (Optional[Annotated[str, "meta"]], Annotated[str, "meta"]),
        (Optional[int | Annotated[str, "meta"]], Annotated[str, "meta"]),
        (Optional[int] | Annotated[str, "meta"], Annotated[str, "meta"]),
        (int | Optional[Annotated[str, "meta"]], Annotated[str, "meta"]),
        (Annotated[str, "meta1"] | Annotated[int, "meta2"], (Annotated[str, "meta1"], Annotated[int, "meta2"])),
        (
            Annotated[str, Constraint(min_len=1)] | Annotated[int, "meta2", Constraint(min=2)],
            (Annotated[str, Constraint(min_len=1)], Annotated[int, "meta2", Constraint(min=2)]),
        ),
    ],
)
def test_get_annotated_type(tp: Any, annotated_type: Any) -> None:
    """Verify that an annotated type that may/may not be nested inside the given type can be retrieved"""
    assert param_type_util.get_annotated_type(tp) == annotated_type


@pytest.mark.parametrize(
    ("tp1", "tp2", "expected_type"),
    [
        (int, int, int),
        (int, str, int | str),
        (int, Optional[str], Optional[int | str]),
        (Literal["1", "2"], Literal["2", "3"], Literal["1", "2", "3"]),
        (Literal["1", "2"], Optional[Literal["2", "3"]], Optional[Literal["1", "2", "3"]]),
        (Annotated[str, "meta1", "meta2"], Annotated[str, "meta2", "meta3"], Annotated[str, "meta1", "meta2", "meta3"]),
        (
            Annotated[str, "meta1", "meta2"],
            Annotated[int, "meta2", "meta3"],
            Annotated[str | int, "meta1", "meta2", "meta3"],
        ),
        (
            Annotated[str, Constraint(nullable=True)],
            Annotated[int, Constraint(nullable=True)],
            Annotated[str | int, Constraint(nullable=True)],
        ),
        (
            Annotated[str, Constraint(nullable=True)],
            Annotated[int, Constraint(nullable=False)],
            Annotated[str, Constraint(nullable=True)] | Annotated[int, Constraint(nullable=False)],
        ),
        (
            Annotated[str, Constraint(nullable=True), Format("foo")],
            Annotated[str, Format("foo"), Constraint(nullable=True)],
            Annotated[str, Constraint(nullable=True), Format("foo")],
        ),
        (
            Annotated[str, "meta1", "meta2"],
            Optional[Annotated[str, "meta3", "meta2"]],
            Optional[Annotated[str, "meta1", "meta2", "meta3"]],
        ),
    ],
)
def test_merge_annotation_types(tp1: Any, tp2: Any, expected_type: Any) -> None:
    """Verify that two annotation types acn be merged"""
    if get_origin(tp1) is Literal or get_origin(tp2) is Literal:
        assert param_type_util.merge_annotation_types(tp1, tp2) != expected_type
        assert repr(param_type_util.merge_annotation_types(tp1, tp2)) == repr(expected_type)
    else:
        assert param_type_util.merge_annotation_types(tp1, tp2) == expected_type


@pytest.mark.parametrize(
    ("tp1", "tp2", "expected_type"),
    [
        (str, str, str),
        (str, int, str | int),
        (str | int, int | str, str | int),
        (str | None, int, str | int | None),
        (MyParamModel, MyParamModel, MyParamModel),
        (MyParamModel, MyParamModel2, MyParamModel),
        (MyParamModel2, MyParamModel3, MyParamModel2),
        (MyParamModel | None, MyParamModel2, MyParamModel | None),
        (MyParamModel, MyParamModel2 | None, MyParamModel | None),
        (MyParamModel2 | None, MyParamModel3, MyParamModel2 | None),
        (MyParamModel2, MyParamModel3 | None, MyParamModel2 | None),
        (MyParamModel, ForwardRef(MyParamModel.__name__), MyParamModel),
    ],
)
def test_custom_or_(tp1: Any, tp2: Any, expected_type: Any) -> None:
    """Verify that our custom `or_` function can treat dynamically created ParamModel instances with the same name as
    the same object
    """
    assert param_type_util.or_(tp1, tp2) == expected_type
