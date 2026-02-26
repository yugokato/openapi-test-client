from dataclasses import dataclass, make_dataclass
from typing import Annotated, Any, cast

import pytest
from _pytest.fixtures import SubRequest

import openapi_test_client.libraries.core.endpoints.utils.param_type as param_type_util
from openapi_test_client.libraries.core.endpoints.utils.pydantic_model import PARAM_FORMAT_AND_TYPE_MAP
from openapi_test_client.libraries.core.types import File, Format, Optional, ParamModel, Unset


@pytest.fixture(scope="session")
def EmptyParamModel() -> type[ParamModel]:
    """A ParamModel that has no attributes"""

    @dataclass
    class Model(ParamModel): ...

    return Model


@pytest.fixture(scope="session")
def RegularParamModel(InnerParamModel: type[ParamModel]) -> type[ParamModel]:
    """A ParamModel that has some attributes and a nested model"""

    @dataclass
    class Model(ParamModel):
        param1: str = Unset
        param2: str = Unset
        param3: InnerParamModel = Unset  # type: ignore[valid-type]

    return Model


@pytest.fixture(scope="session")
def InnerParamModel() -> type[ParamModel]:
    """A ParamModel used for a nested model"""

    @dataclass
    class Model(ParamModel):
        inner_param1: str = Unset
        inner_param2: str = Unset

    return Model


@pytest.fixture
def NewParamModel(request: SubRequest) -> type[ParamModel]:
    """A new dataclass param model generated with requested field data via indirect parametrization

    The fixture can take the field data in various shapes as follows:
    - Just one field:
        - Only field type (field name and the default value will be automatically set)
        - As tuple (field name, field type) or (field name, field type, default value)
    - Multiple fields: List of above
    """
    if not hasattr(request, "param"):
        raise ValueError(f"{NewParamModel.__name__} fixture must be used as an indirect parametrization")

    def add_field(field_data: Any | tuple[str, Any] | tuple[str, Any, Any], idx: int = 1) -> None:
        if isinstance(field_data, tuple):
            assert len(field_data) <= 3, f"Invalid field: {field_data}. Each field must be given as 2 or 3 items"
            if len(field_data) == 1:
                fields.append((f"field_{idx}", field_data, Unset))
            elif len(field_data) >= 2:
                fields.append(field_data)
        else:
            fields.append((f"field{idx}", field_data, Unset))

    requested_field_data = request.param
    fields: list[Any | tuple[str, Any] | tuple[str, Any, Any]] = []
    if isinstance(requested_field_data, list):
        for i, requested_field in enumerate(requested_field_data, start=1):
            add_field(requested_field, idx=i)
    else:
        add_field(requested_field_data)

    param_model = cast(type[ParamModel], make_dataclass("Model", fields, bases=(ParamModel,)))
    return param_model


@pytest.fixture(scope="session")
def ParamModelWithParamFormats() -> type[ParamModel]:
    """A dataclass param model that has fields with various param formats we support"""
    fields = [
        ("uuid", Optional[Annotated[str, Format("uuid")]], Unset),
        ("date_time", Optional[Annotated[str, Format("date-time")]], Unset),
        ("date", Optional[Annotated[str, Format("date")]], Unset),
        ("time", Optional[Annotated[str, Format("time")]], Unset),
        ("duration", Optional[Annotated[str, Format("duration")]], Unset),
        ("binary", Optional[Annotated[str, Format("binary")]], Unset),
        ("file", Optional[Annotated[File, Format("binary")]], Unset),
        ("byte", Optional[Annotated[str, Format("byte")]], Unset),
        ("path", Optional[Annotated[str, Format("path")]], Unset),
        ("base64", Optional[Annotated[str, Format("base64")]], Unset),
        ("base64url", Optional[Annotated[str, Format("base64url")]], Unset),
        ("email", Optional[Annotated[str, Format("email")]], Unset),
        ("name_email", Optional[Annotated[str, Format("name-email")]], Unset),
        ("uri", Optional[Annotated[str, Format("uri")]], Unset),
        ("ipv4", Optional[Annotated[str, Format("ipv4")]], Unset),
        ("ipv6", Optional[Annotated[str, Format("ipv6")]], Unset),
        ("ipvanyaddress", Optional[Annotated[str, Format("ipvanyaddress")]], Unset),
        ("ipvanyinterface", Optional[Annotated[str, Format("ipvanyinterface")]], Unset),
        ("ipvanynetwork", Optional[Annotated[str, Format("ipvanynetwork")]], Unset),
        ("phone", Optional[Annotated[str, Format("phone")]], Unset),
    ]
    param_model = cast(type[ParamModel], make_dataclass("Model", fields, bases=(ParamModel,)))

    # Make sure the model covers all Pydantic specific types we support
    annotated_types = [param_type_util.get_annotated_type(t) for _, t, _ in fields]
    param_formats = [x.__metadata__[0].value for x in annotated_types]
    undefined_formats = set(PARAM_FORMAT_AND_TYPE_MAP.keys()).difference(set(param_formats))
    assert not undefined_formats, f"Missing test coverage for these formats: {undefined_formats}"

    return param_model
