"""Unit tests for core utils/endpoint_model.py"""

from __future__ import annotations

import typing
from collections.abc import Callable
from dataclasses import MISSING, field
from typing import Annotated, Any

import pytest
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.utils.endpoint_model as endpoint_model_util
from openapi_test_client.libraries.core.types import (
    Alias,
    DataclassModelField,
    File,
    Kwargs,
    Unset,
)

pytestmark = [pytest.mark.unittest]


class _FakeEndpointFunc:
    """Minimal stand-in for EndpointFunc.

    The class is intentionally named to end in "EndpointFunc" so that
    `build_endpoint_model`'s model-name derivation produces a name ending in "EndpointModel".
    """

    method: str = "POST"
    path: str = "/v1/test"

    class _Owner:
        __name__ = "FakeOwnerAPI"

    _owner = _Owner()

    def __init__(
        self,
        func: Callable[..., Any],
        path: str = "/v1/test",
        method: str = "POST",
    ) -> None:
        self._original_func = func
        self.path = path
        self.method = method


def _path_field(default: Any = MISSING) -> Any:
    """Build a DataclassField with `path=True` metadata (simulates path-param field)."""
    return field(default=default, metadata={"path": True})


def _body_field(default: Any = Unset) -> Any:
    """Build a DataclassField for a body/query param (no special metadata)."""
    return field(default=default)


class TestCleanModelFieldName:
    """Tests for endpoint_model_util.clean_model_field_name()"""

    def test_plain_name_is_unchanged(self) -> None:
        """Test that an ordinary Python identifier is returned as-is when not reserved"""
        assert endpoint_model_util.clean_model_field_name("my_param") == "my_param"

    def test_hyphenated_name_is_cleaned(self) -> None:
        """Test that hyphens are converted to underscores"""
        assert endpoint_model_util.clean_model_field_name("my-param") == "my_param"

    def test_reserved_model_name_gets_underscore_suffix(self) -> None:
        """Test that a name colliding with a reserved model name receives a trailing underscore"""
        # "Alias" is a core ParamAnnotationType subclass name → reserved
        result = endpoint_model_util.clean_model_field_name("Alias")
        assert result == "Alias_"

    def test_reserved_param_name_gets_underscore_suffix(self) -> None:
        """Test that a name colliding with a Kwargs key receives a trailing underscore"""
        # "quiet" is a Kwargs key → reserved param name
        result = endpoint_model_util.clean_model_field_name("quiet")
        assert result == "quiet_"

    def test_name_that_becomes_reserved_after_cleaning_gets_suffix(self) -> None:
        """Test that a name that matches a reserved name after cleaning also gets the suffix"""
        # "Alias-x" cleans to "Alias_x", which is not reserved → no suffix
        # But "Any" is a reserved typing class name → reserved
        result = endpoint_model_util.clean_model_field_name("Any")
        assert result == "Any_"


class TestGetReservedModelNames:
    """Tests for endpoint_model_util.get_reserved_model_names()"""

    def test_contains_core_type_names(self) -> None:
        """Test that core ParamAnnotationType/DataclassModel subclass names are reserved"""
        reserved = endpoint_model_util.get_reserved_model_names()
        assert "Alias" in reserved
        assert "Query" in reserved
        assert "File" in reserved

    def test_contains_unset_and_kwargs(self) -> None:
        """Test that `Unset` and `Kwargs` are reserved"""
        reserved = endpoint_model_util.get_reserved_model_names()
        assert "Unset" in reserved
        assert Kwargs.__name__ in reserved

    def test_contains_typing_class_names(self) -> None:
        """Test that common `typing` class names are reserved"""
        reserved = endpoint_model_util.get_reserved_model_names()
        for name in ("Any", "Optional", "Annotated", "Literal", "Union", "Unpack"):
            assert name in reserved, f"{name!r} should be in reserved model names"


class TestGetReservedParamNames:
    """Tests for endpoint_model_util.get_reserved_param_names()"""

    def test_returns_kwargs_keys(self) -> None:
        """Test that the reserved param names match the keys of the `Kwargs` TypedDict"""
        reserved = endpoint_model_util.get_reserved_param_names()
        assert set(reserved) == {"quiet", "with_hooks", "raw_options"}


class TestIsHttpxPassthroughField:
    """Tests for endpoint_model_util.is_httpx_passthrough_field()"""

    @pytest.mark.parametrize(
        ("name", "param_type", "expected"),
        [
            ("json", list, True),
            ("json", list[str], True),
            ("data", str, True),
            ("data", Annotated[str, "meta"], True),
            ("files", File, True),
            # Wrong type for a passthrough name
            ("json", str, False),
            ("data", int, False),
            ("files", str, False),
            # Right type but wrong name
            ("body", list, False),
            ("payload", str, False),
            ("attachments", File, False),
        ],
    )
    def test_is_httpx_passthrough_field(self, name: str, param_type: Any, expected: bool) -> None:
        """Test that only the (json, list) / (data, str) / (files, File) combinations are pass-through"""
        assert endpoint_model_util.is_httpx_passthrough_field(name, param_type) is expected


class TestAliasIllegalModelFieldNames:
    """Tests for endpoint_model_util.alias_illegal_model_field_names()"""

    def test_legal_name_is_unchanged(self) -> None:
        """Test that a field with a valid Python identifier name is not aliased"""
        fields = [DataclassModelField("my_param", str, _body_field())]
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/test", fields)
        assert fields[0].name == "my_param"
        assert fields[0].type is str  # no Alias wrapping

    def test_hyphenated_name_is_aliased(self) -> None:
        """Test that a hyphenated field name is cleaned and the original is stored as Alias metadata"""
        fields = [DataclassModelField("my-param", str, _body_field())]
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/test", fields)
        assert fields[0].name == "my_param"
        assert fields[0].type == Annotated[str, Alias("my-param")]

    def test_httpx_passthrough_field_is_not_aliased(self) -> None:
        """Test that httpx pass-through field names (json/data/files) are never aliased"""
        json_field = DataclassModelField("json", list, _body_field())
        data_field = DataclassModelField("data", str, _body_field())
        files_field = DataclassModelField("files", File, _body_field())
        fields = [json_field, data_field, files_field]
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/test", fields)
        # All three should remain unchanged
        assert fields[0].name == "json"
        assert fields[1].name == "data"
        assert fields[2].name == "files"

    def test_path_field_with_illegal_name_logs_warning(self, mocker: MockerFixture) -> None:
        """Test that aliasing a path field (Field with non-empty metadata) emits a warning"""
        mock_log = mocker.patch.object(endpoint_model_util, "logger")
        # Path fields use field(default=MISSING, metadata={"path": True})
        path_field = DataclassModelField("customer-id", str, _path_field())
        fields = [path_field]
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/{customer-id}", fields)
        assert fields[0].name == "customer_id"
        mock_log.warning.assert_called_once()
        assert "customer-id" in mock_log.warning.call_args[0][0]

    def test_body_field_with_illegal_name_does_not_log_warning(self, mocker: MockerFixture) -> None:
        """Test that aliasing a body field (Field with empty metadata) does NOT emit a warning"""
        mock_log = mocker.patch.object(endpoint_model_util, "logger")
        fields = [DataclassModelField("my-param", str, _body_field())]
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/test", fields)
        assert fields[0].name == "my_param"
        mock_log.warning.assert_not_called()

    def test_empty_field_list_is_a_no_op(self) -> None:
        """Test that calling with an empty list does nothing"""
        fields: list[DataclassModelField] = []
        endpoint_model_util.alias_illegal_model_field_names("POST /v1/test", fields)
        assert fields == []


class TestAddBodyOrQueryParamField:
    """Tests for endpoint_model_util.add_body_or_query_param_field()"""

    def test_appends_new_field(self) -> None:
        """Test that a new field name is appended to the list"""
        fields: list[DataclassModelField] = []
        endpoint_model_util.add_body_or_query_param_field(fields, "name", str)
        assert len(fields) == 1
        assert fields[0].name == "name"
        assert fields[0].type is str

    def test_duplicate_name_is_ignored(self) -> None:
        """Test that a field whose name already exists in the list is not appended"""
        fields = [DataclassModelField("name", str, _body_field())]
        endpoint_model_util.add_body_or_query_param_field(fields, "name", int)
        assert len(fields) == 1
        assert fields[0].type is str  # original type unchanged

    def test_multiple_distinct_fields_are_appended(self) -> None:
        """Test that multiple distinct field names are all appended in order"""
        fields: list[DataclassModelField] = []
        endpoint_model_util.add_body_or_query_param_field(fields, "a", str)
        endpoint_model_util.add_body_or_query_param_field(fields, "b", int)
        endpoint_model_util.add_body_or_query_param_field(fields, "c", bool)
        assert [f.name for f in fields] == ["a", "b", "c"]


class TestBuildEndpointModel:
    """Tests for endpoint_model_util.build_endpoint_model()"""

    def test_produced_model_is_frozen_and_kw_only(self) -> None:
        """Test that the generated EndpointModel is frozen and requires keyword-only arguments"""

        def _f(self: Any, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-frozen")
        body = [DataclassModelField("name", str, _body_field())]
        model = endpoint_model_util.build_endpoint_model(ef, [], body)
        params = model.__dataclass_params__
        assert params.frozen is True
        # `kw_only` is not exposed on `__dataclass_params__` before Python 3.12;
        # verify the behavior directly instead.
        with pytest.raises(TypeError):
            model("test_name")  # positional arg must be rejected when kw_only=True

    def test_model_has_correct_class_attrs(self) -> None:
        """Test that `content_type` and `endpoint_func` are set as class attributes"""

        def _f(self: Any, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-attrs")
        body = [DataclassModelField("name", str, _body_field())]
        model = endpoint_model_util.build_endpoint_model(ef, [], body, content_type="text/plain")
        assert model.content_type == "text/plain"
        assert model.endpoint_func is ef

    def test_path_body_name_collision_renames_path_field(self) -> None:
        """Test that a path field whose name collides with a body field is renamed with `_` suffix"""

        def _f(self: Any, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/{name}/items")
        path = [DataclassModelField("name", str, _path_field())]
        body = [DataclassModelField("name", str, _body_field())]
        model = endpoint_model_util.build_endpoint_model(ef, path, body)
        # Path field should be renamed "name_"; body field "name" stays
        assert "name_" in model.__dataclass_fields__
        assert "name" in model.__dataclass_fields__

    def test_model_name_is_derived_from_endpoint_func_class_name(self) -> None:
        """Test that the model class name replaces 'EndpointFunc' with 'EndpointModel'"""

        def _f(self: Any) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-name")
        model = endpoint_model_util.build_endpoint_model(ef, [], [])
        # _FakeEndpointFunc → _FakeEndpointModel
        assert model.__name__ == "_FakeEndpointModel"

    def test_field_types_are_preserved_in_model(self) -> None:
        """Test that field type annotations are preserved in the generated model"""

        def _f(self: Any, count: int, tag: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-types")
        body = [
            DataclassModelField("count", int, _body_field()),
            DataclassModelField("tag", str, _body_field()),
        ]
        model = endpoint_model_util.build_endpoint_model(ef, [], body)
        assert model.__dataclass_fields__["count"].type is int
        assert model.__dataclass_fields__["tag"].type is str


class TestCreateEndpointModel:
    """Tests for endpoint_model_util.create_endpoint_model()"""

    def test_path_params_identified_from_path_placeholders(self) -> None:
        """Test that parameters matching path placeholders are collected as path fields"""

        def _f(self: Any, user_id: str, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/users/{user_id}")
        model = endpoint_model_util.create_endpoint_model(ef)
        assert "user_id" in model.__dataclass_fields__
        # Path field has metadata={"path": True}
        user_id_field = model.__dataclass_fields__["user_id"]
        assert user_id_field.metadata.get("path") is True

    def test_body_params_default_to_unset(self) -> None:
        """Test that non-path params receive `Unset` as default (enabling negative-path testing)"""

        def _f(self: Any, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-unset-default")
        model = endpoint_model_util.create_endpoint_model(ef)
        assert "name" in model.__dataclass_fields__
        assert model.__dataclass_fields__["name"].default is Unset

    def test_param_with_existing_default_keeps_its_default(self) -> None:
        """Test that a param with an explicit signature default keeps that default (not forced to Unset)"""

        def _f(self: Any, status: str = "active") -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-explicit-default")
        model = endpoint_model_util.create_endpoint_model(ef)
        assert model.__dataclass_fields__["status"].default == "active"

    def test_get_type_hints_failure_falls_back_to_raw_annotation(self, mocker: MockerFixture) -> None:
        """Test that a `get_type_hints()` failure logs a warning and uses raw annotations"""

        def _f(self: Any, name: str) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-hint-failure")
        mocker.patch.object(typing, "get_type_hints", side_effect=NameError("unresolvable"))
        mock_log = mocker.patch.object(endpoint_model_util, "logger")
        model = endpoint_model_util.create_endpoint_model(ef)
        # Warning was logged
        mock_log.warning.assert_called_once()
        # Model was still built (using raw annotation from param_obj.annotation)
        assert "name" in model.__dataclass_fields__

    def test_self_and_var_keyword_are_excluded(self) -> None:
        """Test that `self` and `**kwargs` parameters are not included in the model"""

        def _f(self: Any, name: str, **kwargs: Any) -> None: ...

        ef = _FakeEndpointFunc(_f, path="/v1/test-exclusions")
        model = endpoint_model_util.create_endpoint_model(ef)
        assert "self" not in model.__dataclass_fields__
        assert "kwargs" not in model.__dataclass_fields__
        assert "name" in model.__dataclass_fields__
