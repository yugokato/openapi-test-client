"""Unit tests for types.py"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import MISSING, field
from typing import Any

import pytest

from openapi_test_client.libraries.core.types import (
    Alias,
    Constraint,
    DataclassModelField,
    File,
    Format,
    MultipartFormData,
    ParamDef,
    UncacheableLiteralArg,
)

pytestmark = [pytest.mark.unittest]


class TestParamDef:
    """Tests for the ParamDef class (HashableDict subclass)"""

    def test_basic_creation(self) -> None:
        """ParamDef is created from a dict and exposes typed property accessors."""
        p = ParamDef({"type": "string"})
        assert p.type == "string"
        assert p.format is None
        assert p.is_required is False
        assert p.is_deprecated is False
        assert p.is_array is False

    @pytest.mark.parametrize(
        ("obj", "expected_type", "expected_format", "is_required", "is_deprecated"),
        [
            ({"type": "integer"}, "integer", None, False, False),
            ({"type": "boolean", "required": True}, "boolean", None, True, False),
            ({"type": "number", "deprecated": True}, "number", None, False, True),
            ({"type": "string", "format": "email"}, "string", "email", False, False),
            ({"type": "array", "items": {"type": "string"}}, "array", None, False, False),
        ],
    )
    def test_properties(
        self,
        obj: dict[str, str],
        expected_type: str,
        expected_format: str | None,
        is_required: bool,
        is_deprecated: bool,
    ) -> None:
        """Various type/format/required/deprecated combinations are surfaced correctly via properties."""
        p = ParamDef(obj)
        assert p.type == expected_type
        assert p.format == expected_format
        assert p.is_required == is_required
        assert p.is_deprecated == is_deprecated

    def test_constraint_non_array(self) -> None:
        """For non-array types, constraint holds minLength/maxLength/min/max/pattern values."""
        p = ParamDef({"type": "string", "minLength": 1, "maxLength": 255, "pattern": r"\w+"})
        assert p.constraint.min_len == 1
        assert p.constraint.max_len == 255
        assert p.constraint.pattern == r"\w+"
        assert p.constraint.min is None
        assert p.constraint.max is None

    def test_constraint_array(self) -> None:
        """For array types, constraint holds minItems/maxItems mapped to min_len/max_len."""
        p = ParamDef({"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 10})
        assert p.constraint.min_len == 2
        assert p.constraint.max_len == 10

    def test_removes_additional_properties(self) -> None:
        """additionalProperties inside 'properties' is removed during construction."""
        obj = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "additionalProperties": {"type": "string"},
            },
        }
        p = ParamDef(obj)
        assert "additionalProperties" not in p["properties"]
        assert "name" in p["properties"]


class TestParamDefUnknownType:
    """Tests for the ParamDef.UnknownType inner class"""

    def test_creation(self) -> None:
        """UnknownType stores the original param_obj."""
        obj = {"description": "some unknown param"}
        p = ParamDef.UnknownType(obj)
        assert p.param_obj == obj

    def test_asserts_no_type_key(self) -> None:
        """UnknownType raises AssertionError if the obj contains a 'type' key."""
        with pytest.raises(AssertionError):
            ParamDef.UnknownType({"type": "string"})

    def test_is_required(self) -> None:
        """is_required returns True when required=True is set in the obj."""
        p = ParamDef.UnknownType({"description": "x", "required": True})
        assert p.is_required is True

    def test_is_deprecated(self) -> None:
        """is_deprecated returns True when deprecated=True is set in the obj."""
        p = ParamDef.UnknownType({"description": "x", "deprecated": True})
        assert p.is_deprecated is True


class TestParamDefParamGroups:
    """Tests for ParamDef.ParamGroup and its OneOf/AnyOf/AllOf subclasses"""

    @pytest.mark.parametrize("group_class", [ParamDef.OneOf, ParamDef.AnyOf, ParamDef.AllOf])
    def test_oneof_anyof_allof_creation(self, group_class: type) -> None:
        """OneOf/AnyOf/AllOf can be created with a list of ParamDef items."""
        p1 = ParamDef({"type": "string"})
        p2 = ParamDef({"type": "integer"})
        group = group_class([p1, p2])
        assert len(group) == 2
        assert isinstance(group, ParamDef.ParamGroup)

    def test_is_required_propagation(self) -> None:
        """is_required is True when at least one member is required."""
        p_optional = ParamDef({"type": "string"})
        p_required = ParamDef({"type": "integer", "required": True})
        group = ParamDef.OneOf([p_optional, p_required])
        assert group.is_required is True

    def test_is_required_false_when_none_required(self) -> None:
        """is_required is False when no members are required."""
        p1 = ParamDef({"type": "string"})
        p2 = ParamDef({"type": "integer"})
        group = ParamDef.AnyOf([p1, p2])
        assert group.is_required is False


class TestParamDefFromParamObj:
    """Tests for ParamDef.from_param_obj() factory method (unique inputs to avoid lru_cache collisions)"""

    def test_simple_type(self) -> None:
        """A dict with 'type' produces a ParamDef with that type."""
        result = ParamDef.from_param_obj({"type": "string", "_id": "simple"})
        assert isinstance(result, ParamDef)
        assert result.type == "string"

    def test_with_schema_key(self) -> None:
        """A dict with a 'schema' wrapper key has the schema merged and returns a ParamDef."""
        result = ParamDef.from_param_obj({"schema": {"type": "integer"}, "_id": "schema_key"})
        assert isinstance(result, ParamDef)
        assert result.type == "integer"

    def test_oneof(self) -> None:
        """A dict with 'oneOf' key produces a ParamDef.OneOf group."""
        result = ParamDef.from_param_obj({"oneOf": [{"type": "string"}, {"type": "null"}], "_id": "oneof"})
        assert isinstance(result, ParamDef.OneOf)
        assert len(result) == 2
        assert all(isinstance(x, ParamDef) for x in result)

    def test_anyof(self) -> None:
        """A dict with 'anyOf' key produces a ParamDef.AnyOf group."""
        result = ParamDef.from_param_obj({"anyOf": [{"type": "string"}, {"type": "null"}], "_id": "anyof"})
        assert isinstance(result, ParamDef.AnyOf)
        assert len(result) == 2
        assert all(isinstance(x, ParamDef) for x in result)

    def test_allof(self) -> None:
        """A dict with 'allOf' key produces a ParamDef.AllOf group (entries with type/properties kept)."""
        result = ParamDef.from_param_obj(
            {
                "allOf": [
                    {"type": "object", "properties": {"p1": {"type": "string"}}},
                    {"type": "object", "properties": {"p2": {"type": "integer"}}},
                ],
                "_id": "allof",
            }
        )
        assert isinstance(result, ParamDef.AllOf)
        assert len(result) == 2
        assert all(isinstance(x, ParamDef) for x in result)

    def test_array_with_items(self) -> None:
        """An array type has its 'items' value converted to a ParamDef."""
        result = ParamDef.from_param_obj({"type": "array", "items": {"type": "number"}, "_id": "array_items"})
        assert isinstance(result, ParamDef)
        assert result.is_array
        assert isinstance(result["items"], ParamDef)
        assert result["items"].type == "number"

    def test_missing_type_with_properties(self) -> None:
        """A dict with 'properties' but no 'type' key has 'object' assumed as the type."""
        result = ParamDef.from_param_obj({"properties": {"name": {"type": "string"}}, "_id": "missing_type"})
        assert isinstance(result, ParamDef)
        assert result.type == "object"

    def test_unknown_type(self) -> None:
        """A dict with neither 'type' nor 'properties' produces an UnknownType."""
        result = ParamDef.from_param_obj({"description": "opaque param", "_id": "unknown"})
        assert isinstance(result, ParamDef.UnknownType)

    def test_nested_groups(self) -> None:
        """allOf containing oneOf is resolved into nested group structures."""
        result = ParamDef.from_param_obj(
            {
                "allOf": [
                    {"oneOf": [{"type": "string"}, {"type": "null"}]},
                ],
                "_id": "nested_groups",
            }
        )

        assert isinstance(result, ParamDef.AllOf)
        assert len(result) == 1
        assert isinstance(result[0], ParamDef.OneOf)
        assert len(result[0]) == 2


class TestFile:
    """Tests for the File dataclass"""

    def test_creation(self) -> None:
        """File stores filename, content, and content_type."""
        f = File("logo.png", b"\x89PNG", "image/png")
        assert f.filename == "logo.png"
        assert f.content == b"\x89PNG"
        assert f.content_type == "image/png"

    def test_to_tuple(self) -> None:
        """to_tuple() returns (filename, content, content_type)."""
        f = File("doc.pdf", b"%PDF", "application/pdf")
        assert f.to_tuple() == ("doc.pdf", b"%PDF", "application/pdf")

    def test_dict_behavior(self) -> None:
        """File also behaves as a dict (filename/content/content_type are keys)."""
        f = File("img.jpg", b"JFIF", "image/jpeg")
        assert f["filename"] == "img.jpg"
        assert f["content"] == b"JFIF"
        assert f["content_type"] == "image/jpeg"

    def test_string_content(self) -> None:
        """File can hold string content (not just bytes)."""
        f = File("notes.txt", "Hello World", "text/plain")
        assert f.content == "Hello World"
        assert f.to_tuple() == ("notes.txt", "Hello World", "text/plain")


class TestMultipartFormData:
    """Tests for the MultipartFormData MutableMapping wrapper"""

    @pytest.fixture(scope="class")
    def logo(self) -> File:
        return File("logo.png", b"logo-content", "image/png")

    @pytest.fixture(scope="class")
    def favicon(self) -> File:
        return File("favicon.ico", b"fav-content", "image/x-icon")

    @pytest.fixture(scope="class")
    def dict_file(self) -> dict[str, Any]:
        return {"filename": "data.csv", "content": b"col1,col2", "content_type": "text/csv"}

    def test_init_with_file_objects(self, logo: File, favicon: File) -> None:
        """File objects are stored as tuples via File.to_tuple()."""
        files = MultipartFormData(logo=logo, favicon=favicon)
        assert files["logo"] == logo.to_tuple()
        assert files["favicon"] == favicon.to_tuple()

    def test_init_with_dict_objects(self, dict_file: dict[str, Any]) -> None:
        """Dict values are stored as a tuple of their values."""
        files = MultipartFormData(data=dict_file)
        assert files["data"] == tuple(dict_file.values())

    def test_init_skips_falsy_values(self, logo: File) -> None:
        """Entries with falsy file values (None, empty string, etc.) are excluded."""
        files = MultipartFormData(logo=logo, empty=None)
        assert "logo" in files
        assert "empty" not in files
        assert len(files) == 1

    def test_getitem(self, logo: File) -> None:
        """__getitem__ returns the tuple stored under the given key."""
        files = MultipartFormData(logo=logo)
        assert files["logo"] == ("logo.png", b"logo-content", "image/png")

    def test_setitem_file(self, logo: File) -> None:
        """Assigning a File object converts it to a tuple."""
        files = MultipartFormData(logo=logo)
        new_logo = File("new-logo.png", b"new-content", "image/png")
        files["logo"] = new_logo
        assert files["logo"] == new_logo.to_tuple()

    def test_setitem_dict(self, dict_file: dict[str, Any]) -> None:
        """Assigning a dict converts it to a tuple of its values."""
        files = MultipartFormData(data=dict_file)
        new_dict = {"filename": "updated.csv", "content": b"a,b", "content_type": "text/csv"}
        files["data"] = new_dict
        assert files["data"] == tuple(new_dict.values())

    def test_setitem_raw(self, logo: File) -> None:
        """Assigning a raw (non-File, non-dict) value stores it as-is."""
        files = MultipartFormData(logo=logo)
        raw_tuple = ("raw.png", b"raw", "image/png")
        files["logo"] = raw_tuple
        assert files["logo"] == raw_tuple

    def test_delitem(self, logo: File, favicon: File) -> None:
        """Deleting a key removes it; subsequent access raises KeyError."""
        files = MultipartFormData(logo=logo, favicon=favicon)
        del files["logo"]
        assert "logo" not in files
        with pytest.raises(KeyError):
            _ = files["logo"]

    def test_iter(self, logo: File, favicon: File) -> None:
        """Iterating over MultipartFormData yields the key names."""
        files = MultipartFormData(logo=logo, favicon=favicon)
        keys = list(files)
        assert set(keys) == {"logo", "favicon"}

    def test_len(self, logo: File, favicon: File) -> None:
        """len() returns the number of stored files."""
        files = MultipartFormData(logo=logo, favicon=favicon)
        assert len(files) == 2

    def test_to_dict(self, logo: File) -> None:
        """to_dict() returns a plain dict of {name: tuple} pairs."""
        files = MultipartFormData(logo=logo)
        result = files.to_dict()
        assert isinstance(result, dict)
        assert result == {"logo": logo.to_tuple()}

    def test_mutable_mapping_protocol(self, logo: File, favicon: File) -> None:
        """MultipartFormData is a MutableMapping; standard mapping methods work."""
        files = MultipartFormData(logo=logo, favicon=favicon)
        assert isinstance(files, MutableMapping)
        assert set(files.keys()) == {"logo", "favicon"}
        assert len(list(files.values())) == 2
        assert len(list(files.items())) == 2
        for key, value in files.items():
            assert value == files[key]

    def test_string_content(self) -> None:
        """File with string (non-bytes) content is handled without error."""
        text_file = File("notes.txt", "plain text content", "text/plain")
        files = MultipartFormData(notes=text_file)
        assert files["notes"] == text_file.to_tuple()


class TestAlias:
    """Tests for the Alias frozen dataclass"""

    def test_creation(self) -> None:
        """Alias stores its value string."""
        v = "x-param-name"
        a = Alias(v)
        assert a.value == v

    def test_frozen(self) -> None:
        """Alias is frozen; assignment raises FrozenInstanceError."""
        a = Alias("original")
        with pytest.raises(Exception):  # FrozenInstanceError (AttributeError in older Python)
            # noinspection PyDataclass
            a.value = "changed"


class TestFormat:
    """Tests for the Format frozen dataclass"""

    def test_creation(self) -> None:
        """Format stores its value string."""
        v = "date-time"
        f = Format(v)
        assert f.value == v

    def test_frozen(self) -> None:
        """Format is frozen; assignment raises FrozenInstanceError."""
        f = Format("date")
        with pytest.raises(Exception):
            # noinspection PyDataclass
            f.value = "time"


class TestConstraint:
    """Tests for the Constraint frozen dataclass"""

    def test_default_values(self) -> None:
        """All fields default to None."""
        c = Constraint()
        assert c.min is None
        assert c.max is None
        assert c.exclusive_min is None
        assert c.exclusive_max is None
        assert c.multiple_of is None
        assert c.min_len is None
        assert c.max_len is None
        assert c.nullable is None
        assert c.pattern is None

    def test_with_values(self) -> None:
        """Constraint stores the values passed at construction."""
        c = Constraint(min=1, max=100, min_len=3, max_len=50, pattern=r"^\w+$", nullable=True)
        assert c.min == 1
        assert c.max == 100
        assert c.min_len == 3
        assert c.max_len == 50
        assert c.pattern == r"^\w+$"
        assert c.nullable is True

    def test_frozen(self) -> None:
        """Constraint is frozen; assignment raises FrozenInstanceError."""
        c = Constraint(min=0)
        with pytest.raises(Exception):
            # noinspection PyDataclass
            c.min = 999

    def test_repr_filters_none(self) -> None:
        """repr() only shows fields that are not None."""
        c = Constraint(min=1, max=10)
        r = repr(c)
        assert "min=1" in r
        assert "max=10" in r
        assert "min_len" not in r
        assert "pattern" not in r

    def test_repr_empty(self) -> None:
        """repr() for a Constraint with all defaults is 'Constraint()'."""
        c = Constraint()
        assert repr(c) == "Constraint()"


class TestUncacheableLiteralArg:
    """Tests for the UncacheableLiteralArg class"""

    def test_repr(self) -> None:
        """repr() delegates to repr() of the wrapped object."""
        arg = UncacheableLiteralArg("hello")
        assert repr(arg) == repr("hello")

    def test_eq_same_type(self) -> None:
        """Two UncacheableLiteralArgs wrapping equal objects compare equal."""
        a = UncacheableLiteralArg("foo")
        b = UncacheableLiteralArg("foo")
        assert a == b

    def test_eq_different_type(self) -> None:
        """An UncacheableLiteralArg compares equal to its unwrapped value."""
        arg = UncacheableLiteralArg(42)
        assert arg == 42

    def test_eq_not_equal(self) -> None:
        """Two UncacheableLiteralArgs with different values are not equal."""
        a = UncacheableLiteralArg("foo")
        b = UncacheableLiteralArg("bar")
        assert a != b

    def test_hash_uniqueness(self) -> None:
        """Two UncacheableLiteralArgs with the same value have different hashes (id-based)."""
        a = UncacheableLiteralArg("foo")
        b = UncacheableLiteralArg("foo")
        assert hash(a) != hash(b)


class TestDataclassModelField:
    """Tests for the DataclassModelField NamedTuple"""

    def test_creation(self) -> None:
        """DataclassModelField stores name and type with MISSING default."""
        f = DataclassModelField(name="param1", type=str)
        assert f.name == "param1"
        assert f.type is str
        assert f.default is MISSING

    def test_with_default(self) -> None:
        """DataclassModelField stores an explicit default value."""
        default_field = field(default=None)
        f = DataclassModelField(name="optional_param", type=int, default=default_field)
        assert f.name == "optional_param"
        assert f.type is int
        assert f.default is default_field

    def test_is_named_tuple(self) -> None:
        """DataclassModelField supports tuple unpacking via NamedTuple."""
        f = DataclassModelField(name="x", type=float)
        name, tp, default = f
        assert name == "x"
        assert tp is float
        assert default is MISSING
