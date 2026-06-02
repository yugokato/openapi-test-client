"""OpenAPI-specific model types.

This module contains types that are tied to OpenAPI specification concepts:
- ParamDef: raw OpenAPI parameter object data
- ParamModel: the hybrid dataclass+dict model for OpenAPI object-type params
- Format/Constraint: OpenAPI format and constraint annotations
- PydanticModel: base class for strict-validation pydantic models
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import Field, asdict, dataclass, field, is_dataclass, make_dataclass
from functools import lru_cache
from typing import Any, ClassVar, TypeAlias, TypeVar, cast, get_type_hints

from common_libs.decorators import freeze_args
from common_libs.hash import HashableDict
from pydantic import BaseModel, ConfigDict

from openapi_test_client.libraries.core.types import (
    Alias,
    DataclassModel,
    DataclassModelField,
    EndpointModel,
    File,
    MultipartFormData,
    ParamAnnotationType,
    Query,
    RestResponse,
    Unset,
)
from openapi_test_client.libraries.core.types import Kwargs as _Kwargs
from openapi_test_client.libraries.openapi.json_encoder import CustomJsonEncoder

# re-export core types so that openapi related code can import all types from the single location
__all__ = [
    "Alias",
    "Constraint",
    "DataclassModel",
    "DataclassModelField",
    "EndpointModel",
    "File",
    "Format",
    "Kwargs",
    "MultipartFormData",
    "Optional",
    "ParamAnnotationType",
    "ParamDef",
    "ParamModel",
    "PydanticModel",
    "Query",
    "RestResponse",
    "UncacheableLiteralArg",
    "Unset",
]

_T = TypeVar("_T")
# As a workaround for https://github.com/astral-sh/ruff/issues/4858, we temporarily define an alias of typing.Optional
# to avoid UP007 been reported by ruff for API classes and models, where we currently intentionally use `Optional` to
# indicate the endpoint/model parameter is optional. We may switch to use our own custom type for this purpose
# in the future since typing.Optional doesn't actually mean optional, but it just means nullable
Optional: TypeAlias = _T | None


class Kwargs(_Kwargs, total=False):
    """For annotating the `kwargs` param in OpenAPI-based endpoint functions (PEP 692).

    Extends the core.types.Kwargs with OpenAPI-specific control kwargs.
    """

    validate: bool


# All keyword argument names that are consumed by the OpenAPI endpoint function machinery
# (never forwarded to the HTTP layer). Used both for request-wrapper dispatch and for
# reserving these names in the code generator so they are never used as parameter names.
ENDPOINT_FUNC_CONTROL_KWARGS: frozenset[str] = frozenset(get_type_hints(Kwargs))


class PydanticModel(BaseModel):
    """Base class for Pydantic endpoint/param models"""

    model_config: ClassVar = ConfigDict(extra="forbid", validate_assignment=True, strict=True)

    @classmethod
    def validate_as_json(cls: type[PydanticModel], data: dict[str, Any]) -> PydanticModel:
        """Validate parameters as JSON data

        :param data: Dictionary data to validate with this model
        """
        json_data = json.dumps(data, cls=CustomJsonEncoder)
        return cls.model_validate_json(json_data)


class ParamDef(HashableDict):
    """A class to store OpenAPI parameter object data"""

    def __init__(self, obj: dict[str, Any]):
        if "properties" in obj:
            obj["properties"].pop("additionalProperties", None)
        super().__init__(obj)
        if self.is_array:
            self.constraint = Constraint(
                min_len=self.get("minItems"),
                max_len=self.get("maxItems"),
                nullable=self.get("nullable"),
            )
        else:
            self.constraint = Constraint(
                min=self.get("minimum"),
                max=self.get("maximum"),
                exclusive_min=self.get("exclusiveMinimum"),
                exclusive_max=self.get("exclusiveMaximum"),
                multiple_of=self.get("multipleOf"),
                min_len=self.get("minLength"),
                max_len=self.get("maxLength"),
                nullable=self.get("nullable"),
                pattern=self.get("pattern"),
            )

    @property
    def type(self) -> str | list[str]:
        return self["type"]

    @property
    def format(self) -> str | None:
        return self.get("format")

    @property
    def is_required(self) -> bool:
        return self.get("required") is True

    @property
    def is_deprecated(self) -> bool:
        return self.get("deprecated") is True

    @property
    def is_array(self) -> bool:
        return self.type == "array"

    class UnknownType(HashableDict):
        def __init__(self, obj: dict[str, Any]):
            super().__init__(obj)
            assert "type" not in obj
            self.param_obj = obj

        @property
        def is_required(self) -> bool:
            return self.get("required") is True

        @property
        def is_deprecated(self) -> bool:
            return self.get("deprecated") is True

    class ParamGroup(tuple[Any, ...]):
        @property
        def is_required(self) -> bool:
            return any(p.is_required for p in self)

    class OneOf(ParamGroup): ...

    class AnyOf(ParamGroup): ...

    class AllOf(ParamGroup): ...

    @staticmethod
    @freeze_args
    @lru_cache
    def from_param_obj(
        param_obj: Mapping[str, Any] | dict[str, Any] | Sequence[dict[str, Any]],
    ) -> ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType:
        """Convert the parameter object to a ParamDef

        :param param_obj: Raw parameter object from OpenAPI spec
        """

        def convert(obj: Any) -> ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType:
            if isinstance(obj, ParamDef | ParamDef.ParamGroup):
                return obj
            else:
                if "oneOf" in obj:
                    return ParamDef.OneOf([convert(p) for p in obj["oneOf"]])
                elif "anyOf" in obj:
                    return ParamDef.AnyOf([convert(p) for p in obj["anyOf"]])
                elif "allOf" in obj:
                    return ParamDef.AllOf(
                        [
                            convert(p)
                            for p in obj["allOf"]
                            if (
                                any(
                                    key in p.keys()
                                    for key in [
                                        "oneOf",
                                        "anyOf",
                                        "allOf",
                                        "schema",
                                        "type",
                                        "properties",
                                    ]
                                )
                                or p == {}
                            )
                        ]
                    )
                elif "schema" in obj:
                    merged = {k: v for k, v in obj.items() if k != "schema"} | obj["schema"]
                    return convert(merged)
                elif "type" in obj:
                    param_def = ParamDef(obj)
                    if param_def.type == "array" and "items" in param_def:
                        param_def["items"] = convert(param_def["items"])
                    return param_def
                elif "properties" in obj:
                    obj["type"] = "object"
                    return convert(obj)
                else:
                    assert isinstance(obj, dict)
                    return ParamDef.UnknownType(obj)

        return convert(param_obj)


class _ParamModelMeta(type):
    _ORIGINAL_CLASS_ATTR_NAME: ClassVar = "_ORIGINAL_CLASS"
    _ORIGINAL_CLASS: ClassVar = None

    def __instancecheck__(cls, instance: Any) -> bool:
        """Overwrite the behavior of isinstance() for param models

        Our ParamModel class will dynamically recreate a new dataclass model in __new__() for some cases.
        When it happens, the new dataclass model will be created as type `types.<TheClassName>`, which is different
        from the original param model class that is actually defined. To make isinstance() still return True between
        these two, we use the original model class that will be stored in the recreated one's namespace.
        """
        if original_class := getattr(instance, cls._ORIGINAL_CLASS_ATTR_NAME, None):
            return original_class == cls or issubclass(original_class, cls)
        else:
            return type(instance) is cls or issubclass(type(instance), cls)


@dataclass
class ParamModel(dict[str, Any], DataclassModel, metaclass=_ParamModelMeta):
    """Base class for our param model classes for making a dataclass obj to also work as a regular dictionary.

    When validation mode is enabled, the model will be converted to a Pydantic model, and validation in strict mode
    will be performed.

    NOTE:
        - Each field value in a param model will always be defined as Unset
        - Unlike a regular dataclass, our param model will:
            - NOT have any fields that aren't explicitly given (equivalent to Pydantic's exclude_unset=True behavior)
            - take ANY fields if the model class doesn't define any fields (**kwargs behavior)
            - work exactly the same as a regular dictionary
        - For validation mode, fields explicitly typed with `Optional` will be considered as optional.
          Otherwise required

    Examples:
        >>> from dataclasses import dataclass, is_dataclass, asdict
        >>>
        >>> @dataclass
        >>> class Model(ParamModel):
        >>>    param_1: Optional[int] = Unset
        >>>    param_2: int = Unset              # NOTE: This param is required in validation mode
        >>>
        >>> model = Model(param_1=123)
        >>> print(model)
        Model(param_1=123)
        >>> isinstance(model, dict) and is_dataclass(model)
        True
        >>> model.items()
        dict_items([('param_1', 123)])
        >>> dict(model)
        {'param_1': 123}
        >>> asdict(model)
        {'param_1': 123}

        >>> # validation mode:
        >>> import os
        >>> os.environ["VALIDATION_MODE"] = "true"
        >>> model = Model(param_1="123")
        Traceback (most recent call last):
            <snip>
        pydantic_core._pydantic_core.ValidationError: 2 validation errors for Model
        param_1
          Input should be a valid integer [type=int_type, input_value='123', input_type=str]
            For further information visit https://errors.pydantic.dev/2.5/v/int_type
        param_2
          Field required [type=missing, input_value={'param_1': '123'}, input_type=dict]
            For further information visit https://errors.pydantic.dev/2.5/v/missing
    """

    def __new__(cls, **kwargs: Any) -> ParamModel | PydanticModel:
        import openapi_test_client.libraries.openapi.utils.pydantic_model as pydantic_model_util

        model_fields = cls.__dataclass_fields__
        defined_fields = list(model_fields.keys())
        specified_fields = kwargs.keys()
        if pydantic_model_util.is_validation_mode():
            PydanticParamModel = cls.to_pydantic()
            return PydanticParamModel.validate_as_json(kwargs)
        elif (not defined_fields and specified_fields) or (
            set(defined_fields) != set(specified_fields) and set(specified_fields).issubset(set(defined_fields))
        ):
            new_cls = ParamModel.recreate(cls, [(k, type(v), field(default=None)) for k, v in kwargs.items()])
            return new_cls(**kwargs)
        else:
            return super().__new__(cls, **kwargs)

    def __setattr__(self, new_field_name: str, field_value: Any) -> None:
        """Dynamically add a new field to the existing param model and sync with dictionary

        :param new_field_name: A new field name to be added to the model
        :param field_value: The new field value
        """
        model_fields = self.__dataclass_fields__
        this_recreation = new_field_name == "__class__" and is_dataclass(field_value)
        if new_field_name not in model_fields.keys() and not this_recreation:
            existing_fields = [(k, field_obj.type, field(default=None)) for k, field_obj in model_fields.items()]
            new_fields = [(new_field_name, type(field_value), field(default=None))]
            self.__class__ = ParamModel.recreate(type(self), existing_fields + new_fields)  # type: ignore[arg-type]
        super().__setattr__(new_field_name, field_value)

        if not this_recreation:
            super().__setitem__(new_field_name, field_value)

    def __delattr__(self, name: str) -> None:
        """Dynamically remove a field from the existing param model and sync with dictionary

        :param name: A name of an existing field to delete from the model
        """
        model_fields = self.__dataclass_fields__
        if name in model_fields:
            new_fields = [
                (k, field_obj.type, field(default=None)) for k, field_obj in model_fields.items() if k != name
            ]
            self.__class__ = ParamModel.recreate(type(self), new_fields)  # type: ignore[arg-type]
            if name in self:
                super().__delitem__(name)
        else:
            super().__delattr__(name)

    def __setitem__(self, key: str, value: Any) -> None:
        self.__setattr__(key, value)

    def __delitem__(self, key: str) -> None:
        self.__delattr__(key)

    def pop(self, key: str, *args: Any) -> Any:
        """Remove and return value for key; raise KeyError if missing and no default given.

        :param key: The key to remove
        :param args: Optional default value to return if key is not present
        """
        if key not in self:
            if args:
                return args[0]
            raise KeyError(key)
        v = self[key]
        delattr(self, key)
        return v

    def update(self, other: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if other is not None:
            for k, v in other.items() if isinstance(other, Mapping) else other:
                setattr(self, k, v)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def clear(self) -> None:
        for key in list(self.keys()):
            delattr(self, key)

    def popitem(self) -> tuple[str, Any]:
        """Remove and return the last (key, value) pair."""
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(reversed(self))
        value = self[key]
        delattr(self, key)
        return key, value

    def __ior__(self, other: dict[str, Any]) -> ParamModel:
        self.update(other)
        return self

    def copy(self) -> ParamModel:
        """Return a shallow copy as a new ParamModel instance."""
        return type(self)(**dict(self))

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        else:
            self[key] = default
            return default

    @classmethod
    @lru_cache
    def to_pydantic(cls) -> type[PydanticModel]:
        """Convert param model to a Pydantic model for strict validation"""
        import openapi_test_client.libraries.openapi.utils.pydantic_model as pydantic_model_util

        return pydantic_model_util.to_pydantic(cls)

    @classmethod
    def recreate(
        cls,
        current_class: type[ParamModel],
        new_fields: list[tuple[str, Any, Field[Any] | None]],
    ) -> type[ParamModel]:
        """Recreate the model with the new fields

        :param current_class: Current param model class
        :param new_fields: New fields to create a new param model with
        """
        orig_class = getattr(current_class, ParamModel._ORIGINAL_CLASS_ATTR_NAME) or current_class
        return cast(
            type[ParamModel],
            make_dataclass(
                current_class.__name__,
                new_fields,
                bases=(ParamModel,),
                namespace={ParamModel._ORIGINAL_CLASS_ATTR_NAME: orig_class},
            ),
        )


@dataclass(frozen=True, slots=True)
class Format(ParamAnnotationType):
    """OpenAPI parameter format

    Use it as a metadata of typing.Annotated
    """

    value: str


@dataclass(frozen=True, slots=True)
class Constraint(ParamAnnotationType):
    """OpenAPI parameter constraints (maxLength, minLength, etc.)

    Use it as a metadata of typing.Annotated
    """

    min: int | float | None = None
    max: int | float | None = None
    exclusive_min: int | float | None = None
    exclusive_max: int | float | None = None
    multiple_of: int | None = None
    min_len: int | None = None
    max_len: int | None = None
    nullable: bool | None = None
    pattern: str | None = None

    def __repr__(self) -> str:
        const = ", ".join([f"{k}={v}" for k, v in asdict(self).items() if v is not None])
        return f"{type(self).__name__}({const})"


class UncacheableLiteralArg:
    """Make args for typing.Literal uncacheable

    Due to the default cache mechanism implemented in the typing module, the order of arguments for the generated
    Literal type annotation can be unexpected if there's a cache. This behavior causes our dynamic code generation
    unstable if API specs define more than one param objects that have the exact same enum values but in different
    orders. Wrapping each Literal arg value with this class ensures the cached behavior will not happen during the code
    generation.

    eg.
    1. The default behavior of typing module with cache
    >>> from typing import Literal, Optional
    >>> t1 = Literal["foo", "bar"]
    >>> Optional[t1]
    typing.Optional[typing.Literal['foo', 'bar']]
    >>> t2 = Literal["bar", "foo"]
    >>> Optional[t2]
    typing.Optional[typing.Literal['foo', 'bar']]   <--- HERE (Unexpected order due to the cached result)

    2. Uncached behavior
    >>> t1 = Literal[UncacheableLiteralArg("foo"), UncacheableLiteralArg("bar")]
    >>> Optional[t1]
    typing.Optional[typing.Literal['foo', 'bar']]
    >>> t2 = Literal[UncacheableLiteralArg("bar"), UncacheableLiteralArg("foo")]
    >>> Optional[t2]
    typing.Optional[typing.Literal['bar', 'foo']]   <--- HERE (Expected order)
    """

    def __init__(self, obj: Any):
        self.obj = obj

    def __repr__(self) -> str:
        return repr(self.obj)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, UncacheableLiteralArg):
            return self.obj == other.obj
        else:
            return self.obj == other

    def __hash__(self) -> int:
        return id(self)
