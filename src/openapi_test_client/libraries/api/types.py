from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import _DataclassParams  # noqa
from dataclasses import MISSING, Field, asdict, astuple, dataclass, field, is_dataclass, make_dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar, cast

from common_libs.decorators import freeze_args
from common_libs.hash import HashableDict
from pydantic import BaseModel, ConfigDict, create_model

from openapi_test_client.libraries.common.json_encoder import CustomJsonEncoder

if TYPE_CHECKING:
    from typing import Protocol

    from openapi_test_client.libraries.api.api_functions import EndpointFunc
else:
    Protocol = object


class ParamDef(HashableDict):
    """A class to store OpenAPI parameter object data"""

    def __init__(self, obj: dict[str, Any]):
        if "properties" in obj:
            # Remove additionalProperties
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
                exclusive_minimum=self.get("exclusiveMinimum"),
                exclusive_maximum=self.get("exclusiveMaximum"),
                multiple_of=self.get("multipleOf"),
                min_len=self.get("minLength"),
                max_len=self.get("maxLength"),
                nullable=self.get("nullable"),
                pattern=self.get("pattern"),
            )

    @property
    def type(self) -> str:
        return self["type"]

    @property
    def format(self) -> str | None:
        return self.get("format")

    @property
    def is_required(self) -> bool:
        return self.get("required") is True

    @property
    def is_deprecated(self) -> bool:
        return self.get("deprecated", False)

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
            return self.get("deprecated", False)

    class ParamGroup(tuple):
        @property
        def is_required(self) -> bool:
            return any(p.is_required for p in self)

    class OneOf(ParamGroup):
        ...

    class AnyOf(ParamGroup):
        ...

    class AllOf(ParamGroup):
        ...

    @staticmethod
    @freeze_args
    @lru_cache
    def from_param_obj(
        param_obj: Mapping[str, Any] | dict[str, Any] | Sequence[dict[str, Any]]
    ) -> ParamDef | ParamDef.ParamGroup | ParamDef.UnknownType:
        """Convert the parameter object to a ParamDef"""

        def convert(obj: Any):
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
                            if any(
                                key in p.keys() for key in ["oneOf", "anyOf", "allOf", "schema", "type", "properties"]
                            )
                        ]
                    )
                elif "schema" in obj:
                    obj.update(obj["schema"])
                    del obj["schema"]
                    return convert(obj)
                elif "type" in obj:
                    param_def = ParamDef(obj)
                    if param_def.type == "array" and "items" in param_def:
                        param_def["items"] = convert(param_def["items"])
                    return param_def
                elif "properties" in obj:
                    # The parameter type is missing. Assume is is 'object'
                    obj["type"] = "object"
                    return convert(obj)
                else:
                    # Unable to locate parameter type from the param obj
                    assert isinstance(obj, dict)
                    return ParamDef.UnknownType(obj)

        return convert(param_obj)


class PydanticModel(BaseModel):
    """Base class for Pydantic endpoint/param models"""

    model_config: ClassVar = ConfigDict(extra="forbid", validate_assignment=True, strict=True)

    @classmethod
    def validate_as_json(cls: PydanticModel, data: dict[str, Any]) -> PydanticModel:
        """Validate parameters as JSON data

        :param data: Dictionary data to validate with this model
        """
        json_data = json.dumps(data, cls=CustomJsonEncoder)
        return cls.model_validate_json(json_data)


class DataclassModel(Protocol):
    """Base class for endpoint/param models"""

    if TYPE_CHECKING:
        __dataclass_fields__: ClassVar[Mapping[str, Field]]
        __dataclass_params__: ClassVar[_DataclassParams]
        __post_init__: ClassVar[Callable[..., None]]

    @classmethod
    @lru_cache
    def to_pydantic(cls) -> type[PydanticModel]:
        """Convert endpoint/param model to a Pydantic model

        NOTE: For endpoint models, path parameters(positional args) will be excluded from the Pydantic model, since
              they are always required and will be validated earlier at the function call level
        """
        import openapi_test_client.libraries.api.api_functions.utils.pydantic_model as pydantic_model_util

        model_fields = {}
        for field_name, field_obj in cls.__dataclass_fields__.items():
            if field_obj.default is not MISSING:
                model_fields[field_name] = pydantic_model_util.generate_pydantic_model_fields(cls, field_obj.type)

        return cast(
            type[PydanticModel],
            create_model(
                cls.__name__,
                __base__=PydanticModel,
                __module__=cls.__module__,
                **model_fields,
            ),
        )


class EndpointModel(DataclassModel):
    content_type: str | None
    endpoint_func: EndpointFunc


class _ParamModelMeta(type):
    _ORIGINAL_CLASS_ATTR_NAME: ClassVar = "_ORIGINAL_CLASS"
    _ORIGINAL_CLASS: ClassVar = None

    def __instancecheck__(cls, instance: Any):
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
class ParamModel(dict, DataclassModel, metaclass=_ParamModelMeta):
    """Base class for our param model classes for making a dataclass obj to also work as a regular dictionary.

    When validtion mode is enabled, the model will be converted to a Pydantic model, and validation in strict mode will
    be performed.

    NOTE:
        - Each field value in a param model will always be defined as Ellipsis (...)
        - Unlike a regular dataclass, our param model will:
            - NOT have any fields that aren't explicitly given (equivalent to Pydantic's exclude_unset=True behavior)
            - take ANY fields if the model class doesn't define any fields (**kwargs behavior)
            - work exactly the same as a regular dictionary
        - For validaton mode, fields explicitly typed with `Optional` will be considered as optional. Otherwise required

    Examples:
        >>> from dataclasses import dataclass, is_dataclass, asdict
        >>>
        >>> @dataclass
        >>> class Model(ParamModel):
        >>>    param_1: Optional[int] = ...
        >>>    param_2: int = ...               # NOTE: This param is required in validation mode
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

    def __new__(cls, **kwargs):
        import openapi_test_client.libraries.api.api_functions.utils.pydantic_model as pydantic_model_util

        model_fields = cls.__dataclass_fields__
        defined_fields = list(model_fields.keys())
        specified_fields = kwargs.keys()
        if pydantic_model_util.is_validation_mode():
            # Convert the param model to Pydantic model and perform validation in strict mode.
            PydanticParamModel = cls.to_pydantic()
            return PydanticParamModel.validate_as_json(kwargs)
        elif (
            # We change the behavior of dataclass for the following scenarios to make it work more seamlessly as a
            # dictionary:
            # 1. The original param model is defined with no fields, but a user specified arbitrary field(s)
            # 2. Not all param model fields were specified
            #
            # For the case 1, we want to allow the model to take anything (**kwargs behavior) but the native
            # dataclass doesn't naturally support it.
            # For the case 2, we don't want to include any fields where a value (include None) isn't explicitly
            # given. This is important to control API payload whether a parameter with None value should be included
            # or not.
            # For both cases, we dynamically create a new model that has the given fields only
            #
            # case 1
            (not defined_fields and specified_fields)
            or
            # case 2
            (set(defined_fields) != set(specified_fields) and set(specified_fields).issubset(set(defined_fields)))
        ):
            new_cls = ParamModel.recreate(cls, [(k, type(v), field(default=None)) for k, v in kwargs.items()])
            return new_cls(**kwargs)
        else:
            # All model fields were specified
            return super().__new__(cls, **kwargs)

    def __setattr__(self, new_field_name: str, field_value: Any):
        """Dynamically add a new field to the existing param model and sync with dictionary

        :param new_field_name: A new field name to be added to the model
        :param field_value: The new field value
        """
        model_fields = self.__dataclass_fields__
        this_recreation = new_field_name == "__class__" and is_dataclass(field_value)
        if new_field_name not in model_fields.keys() and not this_recreation:
            existing_fields = [(k, field_obj.type, field(default=None)) for k, field_obj in model_fields.items()]
            new_fields = [(new_field_name, type(field_value), field(default=None))]
            self.__class__ = ParamModel.recreate(type(self), existing_fields + new_fields)
        super().__setattr__(new_field_name, field_value)

        if not this_recreation:
            super().__setitem__(new_field_name, field_value)

    def __delattr__(self, name: str):
        """Dynamically remove a field from the existing param model and sync with dictionary

        :param name: A name of an existing field to delete from the model
        """
        model_fields = self.__dataclass_fields__
        if name in model_fields:
            new_fields = [
                (k, field_obj.type, field(default=None)) for k, field_obj in model_fields.items() if k != name
            ]
            self.__class__ = ParamModel.recreate(type(self), new_fields)
            if name in self:
                super().__delitem__(name)
        else:
            super().__delattr__(name)

    def __setitem__(self, key: str, value: Any):
        self.__setattr__(key, value)

    def __delitem__(self, key: str):
        self.__delattr__(key)

    def pop(self, key: str, default: Any = object) -> Any:
        if default is object:
            v = super().pop(key)
        else:
            v = super().pop(key, default)
        if hasattr(self, key):
            delattr(self, key)
        return v

    def update(self, other=None, **kwargs):
        if other is not None:
            for k, v in other.items() if isinstance(other, Mapping) else other:
                setattr(self, k, v)
        else:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        else:
            self[key] = default
            return default

    @classmethod
    def recreate(
        cls, current_class: type[ParamModel], new_fields: list[tuple[str, Any, field | None]]
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
                # Hold the original class as namespace. We will use this in  __instancecheck__() to make the new
                # model look like the original model
                namespace={ParamModel._ORIGINAL_CLASS_ATTR_NAME: orig_class},
            ),
        )


@dataclass
class File(dict, DataclassModel):
    """A file to pass to MultipartFormData class"""

    filename: str
    content: str | bytes
    content_type: str

    def __post_init__(self):
        super().__init__(asdict(self))

    def to_tuple(self) -> tuple[str, str | bytes | str]:
        return astuple(self)  # type: ignore


@dataclass(frozen=True)
class ParamAnnotationType:
    """Base class for all custom classes used for annotating endpoint function parameters"""

    ...


@dataclass(frozen=True)
class Alias(ParamAnnotationType):
    """Alias param name

    Use it as a metadata of typing.Annotated when a param model field name and actual param name need to be different
    (eg. Actual param name contains illegal characters for python variable names)
    """

    value: str


@dataclass(frozen=True)
class Format(ParamAnnotationType):
    """OpenAPI parameter format

    Use it as a metadata of typing.Annotated
    """

    value: str


@dataclass(frozen=True)
class Constraint(ParamAnnotationType):
    """OpenAPI parameter constraints (maxLength, minLength, etc.)

    Use it as a metadata of typing.Annotated
    """

    min: int = None
    max: int = None
    multiple_of: int = None
    min_len: int = None
    max_len: int = None
    nullable: bool = None
    pattern: str = None

    # NOTE: exclusive_minimum/exclusive_maximum are supposed to be a boolean in the OAS 3.x specifications,
    #       but Pydantic currently treats them as an integer
    exclusive_minimum: int = None
    exclusive_maximum: int = None
