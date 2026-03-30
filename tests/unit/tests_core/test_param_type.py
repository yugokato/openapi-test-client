from __future__ import annotations

import sys
from dataclasses import dataclass, make_dataclass
from functools import reduce
from operator import or_
from types import NoneType
from typing import TYPE_CHECKING, Annotated, Any, ForwardRef, Literal, cast, get_args, get_origin

import pytest

import openapi_test_client.libraries.core.endpoints.utils.param_type as param_type_util
from openapi_test_client.libraries.core.types import Alias, Constraint, Format, Optional, ParamDef, ParamModel, Unset

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
        _check_merged_model(merged_model, *orig_models)


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

    def test_replace_annotated_type_raises_when_annotated_tp_to_is_not_annotated(self) -> None:
        """Test that TypeError is raised when annotated_tp_to is not an Annotated[] type"""
        with pytest.raises(TypeError, match="annotated_tp_from and annotated_tp_to must be an Annotated\\[\\] type"):
            param_type_util.replace_annotated_type(Annotated[int, "m"], Annotated[int, "m"], int)


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

    @pytest.mark.parametrize(
        ("tp", "metadata_filter", "expected"),
        [
            # first filter matches
            (Annotated[str, Constraint(min_len=1)], [Constraint], Annotated[str, Constraint(min_len=1)]),
            # second filter matches (regression for early-return bug in loop)
            (Annotated[str, Constraint(min_len=1)], ["nonexistent", Constraint], Annotated[str, Constraint(min_len=1)]),
            # string filter matches
            (Annotated[str, "tag"], "tag", Annotated[str, "tag"]),
            # no filter matches
            (Annotated[str, Constraint(min_len=1)], [Format, "nonexistent"], None),
            # type not annotated
            (str, [Constraint], None),
        ],
    )
    def test_get_annotated_type_with_metadata_filter(self, tp: Any, metadata_filter: list[Any], expected: Any) -> None:
        """Test that get_annotated_type correctly filters annotated types by metadata"""
        assert param_type_util.get_annotated_type(tp, metadata_filter=metadata_filter) == expected


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

    def test_merge_annotation_types_as_union(self) -> None:
        """Test that types where only one of type annotations has ParamAnnotationType metadata are treated as a union,
        not merged
        """
        tp1 = Annotated[str, Constraint(nullable=True)]
        tp2 = Annotated[int, "meta"]
        result = param_type_util.merge_annotation_types(tp1, tp2)
        assert result == tp1 | tp2


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
        _check_merged_model(merged_model, model1, model2)


class TestResolveTypeAnnotation:
    """Tests for param_type_util.resolve_type_annotation()"""

    @pytest.mark.parametrize(
        ("openapi_type", "expected"),
        [
            ("string", str),
            ("str", str),  # non-standard but handled
            ("integer", int),
            ("int", int),  # non-standard but handled
            ("int32", int),
            ("int64", int),
            ("boolean", bool),
            ("bool", bool),  # non-standard but handled
        ],
    )
    def test_basic_scalar_types_returns_correct_python_type(self, openapi_type: str, expected: type) -> None:
        """Test that basic OpenAPI scalar types are resolved to the corresponding Python type."""
        param_def = _make_param_def({"type": openapi_type, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is expected

    def test_number_type_without_format_returns_int_or_float(self) -> None:
        """Test that number type without a format resolves to int | float."""
        param_def = _make_param_def({"type": "number", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == int | float

    @pytest.mark.parametrize("number_format", ["float", "double"])
    def test_number_type_with_float_format_returns_float(self, number_format: str) -> None:
        """Test that number type with float/double format resolves to float."""
        param_def = _make_param_def({"type": "number", "format": number_format, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is float

    def test_null_type_returns_none(self) -> None:
        """Test that null type resolves to None."""
        param_def = _make_param_def({"type": "null", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is None

    def test_string_with_format_returns_annotated_str(self) -> None:
        """Test that a string type with a format resolves to Annotated[str, Format(...)]."""
        param_def = _make_param_def({"type": "string", "format": "uuid", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == Annotated[str, Format("uuid")]

    def test_integer_with_format_returns_annotated_int(self) -> None:
        """Test that an integer type with a format resolves to Annotated[int, Format(...)]."""
        param_def = _make_param_def({"type": "int64", "format": "int64", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == Annotated[int, Format("int64")]

    def test_required_param_is_not_optional(self) -> None:
        """Test that a required parameter is not wrapped with Optional."""
        param_def = _make_param_def({"type": "string", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is str

    def test_optional_param_is_wrapped_with_optional(self) -> None:
        """Test that a non-required parameter is wrapped with Optional."""
        param_def = _make_param_def({"type": "string"})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=False)
        assert result == str | None

    def test_param_without_required_flag_defaults_to_optional(self) -> None:
        """Test that a parameter without a required flag is treated as optional."""
        param_def = _make_param_def({"type": "integer"})
        result = param_type_util.resolve_type_annotation("param", param_def)
        assert result == int | None

    def test_is_required_true_overrides_param_def_not_required(self) -> None:
        """Test that _is_required=True prevents Optional wrapping even when param_def.is_required is False."""
        param_def = _make_param_def({"type": "string"})  # not required by default
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is str

    def test_array_with_string_items_returns_list_of_str(self) -> None:
        """Test that an array type with string items resolves to list[str]."""
        param_def = _make_param_def({"type": "array", "items": {"type": "string"}, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == list[str]

    def test_array_with_integer_items_returns_list_of_int(self) -> None:
        """Test that an array type with integer items resolves to list[int]."""
        param_def = _make_param_def({"type": "array", "items": {"type": "integer"}, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == list[int]

    def test_array_without_items_returns_list_of_any(self) -> None:
        """Test that an array type with no items definition resolves to list[Any]."""
        param_def = _make_param_def({"type": "array", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == list[Any]

    def test_nested_array_resolves_correctly(self) -> None:
        """Test that a nested array (array of array of strings) resolves to list[list[str]]."""
        param_def = _make_param_def(
            {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "required": True}
        )
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == list[list[str]]

    def test_object_type_without_properties_returns_dict(self) -> None:
        """Test that an object type without properties resolves to dict[str, Any]."""
        param_def = _make_param_def({"type": "object", "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result == dict[str, Any]

    def test_object_type_with_properties_returns_param_model(self) -> None:
        """Test that an object type with properties resolves to a ParamModel subclass."""
        param_def = _make_param_def(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": True,
            }
        )
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert param_type_util.is_param_model(result, include_forward_ref=False)
        assert issubclass(result, ParamModel)

    def test_enum_resolves_to_literal_type(self) -> None:
        """Test that a parameter with an enum resolves to a Literal type containing all enum values."""
        from openapi_test_client.libraries.core.types import UncacheableLiteralArg

        param_def = _make_param_def({"type": "string", "enum": ["a", "b", "c"], "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert get_origin(result) is Literal
        # Args are wrapped in UncacheableLiteralArg; unwrap to get the actual values
        raw_args = {arg.obj if isinstance(arg, UncacheableLiteralArg) else arg for arg in get_args(result)}
        assert raw_args == {"a", "b", "c"}

    def test_deprecated_param_is_annotated_with_deprecated_metadata(self) -> None:
        """Test that a deprecated parameter has 'deprecated' in its Annotated metadata."""
        param_def = _make_param_def({"type": "string", "deprecated": True, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert param_type_util.is_deprecated_param(result)

    def test_param_with_constraint_is_annotated(self) -> None:
        """Test that a parameter with constraints is wrapped with Annotated[..., Constraint(...)]."""
        param_def = _make_param_def({"type": "integer", "minimum": 1, "maximum": 100, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        annotated = param_type_util.get_annotated_type(result)
        assert annotated is not None
        constraint = next((m for m in annotated.__metadata__ if isinstance(m, Constraint)), None)
        assert constraint is not None
        assert constraint.min == 1
        assert constraint.max == 100

    def test_string_with_length_constraint_is_annotated(self) -> None:
        """Test that a string with length constraints is wrapped with Annotated[..., Constraint(...)]."""
        param_def = _make_param_def({"type": "string", "minLength": 2, "maxLength": 50, "required": True})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        annotated = param_type_util.get_annotated_type(result)
        assert annotated is not None
        constraint = next((m for m in annotated.__metadata__ if isinstance(m, Constraint)), None)
        assert constraint is not None
        assert constraint.min_len == 2
        assert constraint.max_len == 50

    def test_any_of_param_resolves_to_union_type(self) -> None:
        """Test that an anyOf parameter group resolves to a union of the member types."""
        param_def = _make_param_def({"anyOf": [{"type": "string"}, {"type": "integer"}]})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert param_type_util.is_union_type(result, exclude_optional=True)
        base = param_type_util.get_base_type(result)
        assert param_type_util.is_union_type(base, exclude_optional=True)
        assert str in get_args(base)
        assert int in get_args(base)

    def test_one_of_param_resolves_to_union_type(self) -> None:
        """Test that a oneOf parameter group resolves to a union of the member types."""
        param_def = _make_param_def({"oneOf": [{"type": "boolean"}, {"type": "string"}]})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert param_type_util.is_union_type(result, exclude_optional=True)
        base = param_type_util.get_base_type(result)
        assert param_type_util.is_union_type(base, exclude_optional=True)
        assert bool in get_args(base)
        assert str in get_args(base)

    def test_unknown_type_resolves_to_any(self) -> None:
        """Test that a parameter object with no recognizable type resolves to Any."""
        # A dict with no 'type' key produces a ParamDef.UnknownType
        param_def = _make_param_def({"description": "no type here"})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert result is Any

    def test_raw_dict_input_is_converted_and_resolved(self) -> None:
        """Test that passing a plain dict (not a ParamDef) is handled by converting it internally."""
        # resolve_type_annotation accepts non-ParamDef and converts it via from_param_obj
        raw = {"type": "string", "required": True}
        result = param_type_util.resolve_type_annotation("param", raw, _is_required=True)
        assert result is str

    def test_unsupported_type_raises_not_implemented_error(self) -> None:
        """Test that an unsupported OpenAPI type raises NotImplementedError."""
        param_def = _make_param_def({"type": "unsupported_type", "required": True})
        with pytest.raises(NotImplementedError, match="Unsupported type"):
            param_type_util.resolve_type_annotation("param", param_def, _is_required=True)

    def test_all_of_param_resolves_to_union_type(self) -> None:
        """Test that an allOf parameter group resolves to a union type.

        Note: allOf is semantically an intersection but is currently treated as a union.
        """
        param_def = _make_param_def({"allOf": [{"type": "string"}, {"type": "integer"}]})
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert param_type_util.is_union_type(result, exclude_optional=True)
        base = param_type_util.get_base_type(result)
        assert param_type_util.is_union_type(base, exclude_optional=True)
        assert str in get_args(base)
        assert int in get_args(base)

    def test_array_with_oneof_items_resolves_to_list_of_union(self) -> None:
        """Test that an array type with oneOf items resolves to list[union_type]."""
        param_def = _make_param_def(
            {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "integer"}]}, "required": True}
        )
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert get_origin(result) is list
        inner = get_args(result)[0]
        assert param_type_util.is_union_type(inner, exclude_optional=True)
        assert str in get_args(inner)
        assert int in get_args(inner)

    def test_array_with_anyof_items_resolves_to_list_of_union(self) -> None:
        """Test that an array type with anyOf items resolves to list[union_type]."""
        param_def = _make_param_def(
            {"type": "array", "items": {"anyOf": [{"type": "boolean"}, {"type": "string"}]}, "required": True}
        )
        result = param_type_util.resolve_type_annotation("param", param_def, _is_required=True)
        assert get_origin(result) is list
        inner = get_args(result)[0]
        assert param_type_util.is_union_type(inner, exclude_optional=True)
        assert bool in get_args(inner)
        assert str in get_args(inner)


def _check_merged_model(merged_model: type[ParamModel], *original_models: type[ParamModel]) -> None:
    assert set((name, f.name, f.type, f.default) for name, f in merged_model.__dataclass_fields__.items()) == {
        *((name, f.name, f.type, f.default) for m in original_models for name, f in m.__dataclass_fields__.items()),
    }


def _make_param_def(obj: dict[str, Any]) -> ParamDef:
    """Helper to build a ParamDef from a raw OpenAPI parameter dict."""
    return ParamDef.from_param_obj(obj)
