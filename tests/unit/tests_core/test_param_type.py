from __future__ import annotations

import sys
from dataclasses import dataclass, make_dataclass
from functools import reduce
from operator import or_
from types import NoneType
from typing import TYPE_CHECKING, Annotated, Any, ForwardRef, Literal, cast, get_args, get_origin

import pytest

import openapi_test_client.libraries.core.endpoints.utils.param_type as param_type_util
from openapi_test_client.libraries.core.types import Alias, Constraint, Format, Optional, ParamModel, Unset

if TYPE_CHECKING:
    from typing import _AnnotatedAlias  # type: ignore[attr-defined]

pytestmark = [pytest.mark.unittest]


class MyClass: ...


@dataclass
class MyParamModel(ParamModel):
    param1: str = Unset
    param2: str = Unset


MyParamModel2 = cast(
    type[ParamModel], make_dataclass(MyParamModel.__name__, [("foo", str, Unset)], bases=(ParamModel,))
)
MyParamModel3 = cast(
    type[ParamModel], make_dataclass(MyParamModel.__name__, [("bar", int, Unset)], bases=(ParamModel,))
)
MyAnotherParamModel = cast(
    type[ParamModel], make_dataclass("MyAnotherParamModel", [("foobar", int, Unset)], bases=(ParamModel,))
)


class TestGetBaseType:
    """Tests for param_type_util.get_base_type()"""

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
            (list[list[str]], list[str]),
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
    def test_get_base_type(self, tp: Any, expected_type: Any) -> None:
        """Test that the base type can be identified from various type annotations"""
        assert param_type_util.get_base_type(tp) == expected_type


class TestReplaceBaseType:
    """Tests for param_type_util.replace_base_type()"""

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
            (list[list[str]], int, list[int]),
            (list[list[str]], list[int], list[list[int]]),
            (tuple[str, int], (bool, float), tuple[bool, float]),
            (Optional[str], int, Optional[int]),
            (Optional[str | int], bool, Optional[bool]),
            (Optional[dict[str, Any]], MyParamModel, Optional[MyParamModel]),
            (Optional[ForwardRef(MyParamModel.__name__)], str, Optional[str]),
            (Optional[list[list[str]]], list[int], Optional[list[list[int]]]),
            (Annotated[str, "meta", Constraint(min=1)], int, Annotated[int, "meta", Constraint(min=1)]),
            (Annotated[str | int, "meta"], bool, Annotated[bool, "meta"]),
            (Annotated[list[list[str]], "meta"], list[int], Annotated[list[list[int]], "meta"]),
            (Optional[Annotated[str, "meta"]], int, Optional[Annotated[int, "meta"]]),
            (Optional[Annotated[dict[str, Any], "meta"]], MyParamModel, Optional[Annotated[MyParamModel, "meta"]]),
            (Optional[Annotated[list[list[str]], "meta"]], list[int], Optional[Annotated[list[list[int]], "meta"]]),
            (Optional[Annotated[ForwardRef(MyParamModel.__name__), "meta"]], str, Optional[Annotated[str, "meta"]]),
        ],
    )
    def test_replace_baser_type(self, tp: Any, replace_with: Any, expected_type: Any) -> None:
        """Test that the base type of the type annotation can be replaced with another type"""
        assert param_type_util.replace_base_type(tp, replace_with) == expected_type


class TestIsTypeOf:
    """Tests for param_type_util.is_type_of()"""

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
    def test_is_type_of(self, param_type: Any, type_to_check: Any, is_type_of: bool) -> None:
        """Test that we can check if a specific Python type falls into an OpenAPI parameter type or a Python type"""
        assert param_type_util.is_type_of(param_type, type_to_check) is is_type_of


class TestIsOptionalType:
    """Tests for param_type_util.is_optional_type()"""

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
    def test_is_optional_type(self, tp: Any, is_optional_type: bool) -> None:
        """Test that we can check whether a given type annotation can be used for an optional parameter type or not

        Note: The definition of optional here means either Optional[] or a union type with None as one of the args
        """
        assert param_type_util.is_optional_type(tp) is is_optional_type


class TestIsUnionType:
    """Tests for param_type_util.is_union_type()"""

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
    def test_is_union_type(self, tp: Any, is_union_type: bool, exclude_optional: bool) -> None:
        """Test that we can check whether a given type annotation itself is a union type or not

        Note: Optional[] is also considered as union
        """
        if exclude_optional:
            is_union = is_union_type and NoneType not in get_args(tp)
        else:
            is_union = is_union_type
        assert param_type_util.is_union_type(tp, exclude_optional=exclude_optional) is is_union


class TestIsDeprecatedParam:
    """Tests for param_type_util.is_deprecated_param()"""

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
    def test_is_deprecated_param(self, tp: Any, is_deprecated_param: bool) -> None:
        """Test that we can check whether a given type annotation has `Annotated[]` with "deprecated" in the metadata"""
        assert param_type_util.is_deprecated_param(tp) is is_deprecated_param


class TestGenerateUnionType:
    """Tests for param_type_util.generate_union_type()"""

    @pytest.mark.parametrize(
        ("types", "expected_type"),
        [
            ([None], None),
            ([str], str),
            ([str, str], str),
            ([str, int], str | int),
            ([str, int, None], str | int | None),
            ([str, int, None, str, int, None], str | int | None),
            ([MyParamModel, MyAnotherParamModel, str | int], MyParamModel | MyAnotherParamModel | str | int),
            ([], Any),
        ],
    )
    def test_generate_union_type(self, types: list[Any], expected_type: Any) -> None:
        """Test that a union type annotation can be generated from multiple type annotations"""
        assert param_type_util.generate_union_type(types) == expected_type

    @pytest.mark.parametrize(
        "types",
        [
            [MyParamModel, MyParamModel, str | int],
            [MyParamModel2, MyParamModel3, str | int],
            [MyParamModel, MyParamModel2, MyParamModel3, str | int],
        ],
    )
    def test_generate_union_type_with_model_merge(self, types: list[Any]) -> None:
        """Test that a union type annotation can be generated from multiple type annotations with model merging"""
        tp = param_type_util.generate_union_type(types)
        orig_models = [x for x in types if param_type_util.is_param_model(x)]
        merged_model = param_type_util.get_param_model(tp)
        check_merged_model(merged_model, *orig_models)


class TestGenerateOptionalType:
    """Tests for param_type_util.generate_optional_type()"""

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
    def test_generate_optional_type(self, tp: Any, expected_type: Any) -> None:
        """Test that a type annotation can be converted to an optional type with Optional[]"""
        assert param_type_util.generate_optional_type(tp) == expected_type


class TestGenerateLiteralType:
    """Tests for param_type_util.generate_literal_type()"""

    @pytest.mark.parametrize("uncacheable", [True, False])
    def test_generate_literal_type(self, uncacheable: bool) -> None:
        """Test that a literal type annotation can be generated with/without the typing module's caching mechanism"""
        args1 = ["1", "2", "2", "3"]
        args2 = ["3", "2", "1", "2"]
        tp1 = param_type_util.generate_literal_type(*args1, uncacheable=uncacheable)
        tp2 = param_type_util.generate_literal_type(*args2, uncacheable=uncacheable)

        if uncacheable:
            assert tp1 != tp2
        else:
            assert Literal[*args1] == tp1 == tp2

        if sys.version_info >= (3, 14, 0):
            # There is a change around Union and repr() in 3.14
            # https://docs.python.org/3/whatsnew/3.14.html#typing
            assert repr(Optional[tp1]) == "typing.Literal['1', '2', '3'] | None"
            assert repr(Optional[tp2]) == "typing.Literal['3', '2', '1'] | None"
        else:
            if uncacheable:
                assert repr(Optional[tp1]) == "typing.Optional[typing.Literal['1', '2', '3']]"
                assert repr(Optional[tp2]) == "typing.Optional[typing.Literal['3', '2', '1']]"
            else:
                # NOTE: This is the default behavior of typing.Literal
                assert repr(Optional[tp1]) == repr(Optional[tp2]) == "typing.Optional[typing.Literal['1', '2', '3']]"


class TestAnnotateType:
    """Tests for param_type_util.annotate_type()"""

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
    def test_annotate_type(self, tp: Any, metadata: list[Any], expected_type: Any) -> None:
        """Test that a type annotation can be converted to an annotated type with metadata"""
        assert param_type_util.annotate_type(tp, *metadata) == expected_type


class TestReplaceAnnotatedType:
    """Tests for param_type_util.replace_annotated_type()"""

    @pytest.mark.parametrize(
        ("tp", "annotated_from", "annotated_to", "expected_type"),
        [
            (Annotated[int, "m"], Annotated[int, "m"], Annotated[str, "m", "m2"], Annotated[str, "m", "m2"]),
            (
                Optional[Annotated[int, "m"]],
                Annotated[int, "m"],
                Annotated[str, "m2"],
                Optional[Annotated[str, "m2"]],
            ),
            (Annotated[int, "m"], Annotated[int, "m"], Annotated[int | str, "m2"], Annotated[int | str, "m2"]),
            (list[Annotated[int, "m"]], Annotated[int, "m"], Annotated[str, "m"], list[Annotated[str, "m"]]),
            (
                Annotated[list[Annotated[list[int], Constraint(min_len=3)]], Constraint(min_len=1)],
                Annotated[list[int], Constraint(min_len=3)],
                Annotated[list[str], Constraint(min=2), "m"],
                Annotated[list[Annotated[list[str], Constraint(min=2), "m"]], Constraint(min_len=1)],
            ),
        ],
    )
    def test_replace_annotated_type(
        self, tp: Any, annotated_from: _AnnotatedAlias, annotated_to: _AnnotatedAlias, expected_type: Any
    ) -> None:
        """Test that Annotated[] type inside a type annotation can be replaced with another Annotated[] type"""
        assert param_type_util.replace_annotated_type(tp, annotated_from, annotated_to) == expected_type


class TestModifyAnnotatedMetadata:
    """Tests for param_type_util.modify_annotated_metadata() with add/remove/replace actions"""

    @pytest.mark.parametrize(
        ("tp", "metadata", "expected_type"),
        [
            (Annotated[str, "meta1"], ["meta2"], Annotated[str, "meta1", "meta2"]),
            (Annotated[str, "meta1", "meta2"], ["meta2", "meta3"], Annotated[str, "meta1", "meta2", "meta3"]),
            (Optional[Annotated[str, "meta1"]], ["meta2"], Optional[Annotated[str, "meta1", "meta2"]]),
            (Optional[Annotated[str | int, "meta1"]], ["meta2"], Optional[Annotated[str | int, "meta1", "meta2"]]),
            (
                Annotated[list[Annotated[list[int], Constraint(min_len=3)]], Constraint(min_len=1)],
                ["meta1"],
                Annotated[list[Annotated[list[int], Constraint(min_len=3)]], Constraint(min_len=1), "meta1"],
            ),
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
    def test_add_annotated_metadata(self, tp: Any, metadata: list[Any], expected_type: Any) -> None:
        """Test that new metadata can be added to existing ones in the annotated type"""
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
    def test_remove_annotated_metadata(self, tp: Any, metadata: list[Any], expected_type: Any) -> None:
        """Test that one or more metadata in the annotated type can be removed"""
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
    def test_replace_annotated_metadata(self, tp: Any, metadata: list[Any], expected_type: Any) -> None:
        """Test that metadata in the annotated type can be replaced with new value(s)"""
        assert param_type_util.modify_annotated_metadata(tp, *metadata, action="replace") == expected_type


class TestGetAnnotatedType:
    """Tests for param_type_util.get_annotated_type()"""

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
    def test_get_annotated_type(self, tp: Any, annotated_type: Any) -> None:
        """Test that an annotated type that may/may not be nested inside the given type can be retrieved"""
        assert param_type_util.get_annotated_type(tp) == annotated_type


class TestMergeAnnotationTypes:
    """Tests for param_type_util.merge_annotation_types()"""

    @pytest.mark.parametrize(
        ("tp1", "tp2", "expected_type"),
        [
            (int, int, int),
            (int, str, int | str),
            (int, Optional[str], Optional[int | str]),
            (Literal["1", "2"], Literal["2", "3"], Literal["1", "2", "3"]),
            (Literal["1", "2"], Optional[Literal["2", "3"]], Optional[Literal["1", "2", "3"]]),
            (
                Annotated[str, "meta1", "meta2"],
                Annotated[str, "meta2", "meta3"],
                Annotated[str, "meta1", "meta2", "meta3"],
            ),
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
    def test_merge_annotation_types(self, tp1: Any, tp2: Any, expected_type: Any) -> None:
        """Test that two annotation types can be merged"""
        if get_origin(tp1) is Literal or get_origin(tp2) is Literal:
            assert param_type_util.merge_annotation_types(tp1, tp2) != expected_type
            assert repr(param_type_util.merge_annotation_types(tp1, tp2)) == repr(expected_type)
        else:
            assert param_type_util.merge_annotation_types(tp1, tp2) == expected_type


class TestMatchesType:
    """Tests for param_type_util.matches_type()"""

    @pytest.mark.parametrize(
        ("value", "tp", "is_valid"),
        [
            # valid
            (None, Optional[int], True),
            (1, Any, True),
            (1, int, True),
            (1, int | str, True),
            (1, Optional[int], True),
            (1, Optional[int | str], True),
            (1, Optional[Annotated[int, "meta"]], True),
            (1, Optional[Annotated[int | str, "meta"]], True),
            (1, Literal[1, 2], True),
            ([1, 2], Any, True),
            ([1, 2], list[int], True),
            ([1, "2"], list[int | str], True),
            ({"k": "v"}, Any, True),
            ({}, dict[str, Any], True),
            ({"k": "v"}, dict[str, str], True),
            ({"k": "v"}, dict[str | int, str], True),
            (MyParamModel(), MyParamModel, True),
            (MyParamModel(), dict, True),
            (MyParamModel(param1="foo"), dict[str, str], True),
            (MyParamModel(), dict | ParamModel, True),
            ({"k": "v"}, MyParamModel | dict[str, Any], True),
            # invalid
            (None, int, False),
            (1, str, False),
            (1, str | bool, False),
            (1, Optional[str], False),
            (1, Optional[str | bool], False),
            (1, Optional[Annotated[str, "meta"]], False),
            (1, Optional[Annotated[str | bool, "meta"]], False),
            (1, Literal[2, 3], False),
            ([1, 2], int, False),
            ([1, 2], list[str], False),
            ([1, "2"], list[str], False),
            ([1, 2], list[str | bool], False),
            ({"k": 1}, dict[str, str], False),
            ({1: "v"}, dict[str, str], False),
            ({1: 2}, dict[str, str], False),
            ({}, MyParamModel, False),
            (MyParamModel(param1="foo"), dict[str, int], False),
        ],
    )
    def test_matches_type(self, value: Any, tp: Any, is_valid: bool) -> None:
        """Test that a value can be validated if it conforms to the type annotation"""
        assert param_type_util.matches_type(value, tp) is is_valid


class TestCustomOr:
    """Tests for the custom param_type_util.or_() function"""

    @pytest.mark.parametrize(
        ("tp1", "tp2", "expected_type"),
        [
            (str, str, str),
            (str, int, str | int),
            (str | int, int | str, str | int),
            (str | None, int, str | int | None),
            (MyParamModel, MyAnotherParamModel, MyParamModel | MyAnotherParamModel),
        ],
    )
    def test_custom_or_with_no_model_merge(self, tp1: Any, tp2: Any, expected_type: Any) -> None:
        """Test that our custom `or_` function should work the same as operator.or_ when no model merge is needed"""
        assert param_type_util.or_(tp1, tp2) == reduce(or_, [tp1, tp2]) == expected_type

    @pytest.mark.parametrize(
        ("tp1", "tp2"),
        [
            (MyParamModel, MyParamModel),
            (MyParamModel2, MyParamModel3),
            (MyParamModel | None, MyParamModel2),
            (MyParamModel, MyParamModel2 | None),
            (MyParamModel2 | None, MyParamModel3),
            (MyParamModel2, MyParamModel3 | None),
        ],
    )
    def test_custom_or_with_model_merge(self, tp1: Any, tp2: Any) -> None:
        """Test that our custom `or_` function merges param models with the same name"""
        model1 = param_type_util.get_param_model(tp1)
        model2 = param_type_util.get_param_model(tp2)
        assert model1 and model2

        tp = param_type_util.or_(tp1, tp2)
        merged_model = param_type_util.get_param_model(tp)
        assert merged_model
        check_merged_model(merged_model, model1, model2)


def check_merged_model(merged_model: type[ParamModel], *original_models: type[ParamModel]) -> None:
    assert set((name, f.name, f.type, f.default) for name, f in merged_model.__dataclass_fields__.items()) == {
        *((name, f.name, f.type, f.default) for m in original_models for name, f in m.__dataclass_fields__.items()),
    }
