import base64
import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

import pytest
from pydantic import ValidationError
from pytest_lazy_fixtures import lf as lazy_fixture

import openapi_test_client.libraries.api.api_functions.utils.param_type as param_type_util
from openapi_test_client.libraries.api.types import Constraint, Optional, ParamModel, PydanticModel

pytestmark = [pytest.mark.unittest]


@pytest.mark.parametrize(
    ("NewParamModel", "input_value"),
    [
        (str, "foo"),
        (str | int, "foo"),
        (str | int, 123),
        (Literal["1", "2"], "2"),
        (Literal["1", "2"] | int, 3),
        (Annotated[str, "meta"], "foo"),
        (Annotated[str | int, "meta"], "foo"),
        (Annotated[str | int, "meta"], 123),
        (Annotated[str, Constraint(pattern=r"^test\d+$")], "test123"),
        (
            Annotated[str, Constraint(pattern=r"^test\d+$")] | Annotated[str, Constraint(pattern=r"^\d+test$")],
            "123test",
        ),
        (Annotated[str, Constraint(min_len=2)] | Annotated[int, Constraint(min=2)], "test"),
        (Annotated[str, Constraint(min_len=2)] | Annotated[int, Constraint(min=2)], 3),
        (Annotated[str, Constraint(nullable=True)], None),
        (Annotated[list[str], Constraint(min_len=2)], ["foo", "bar"]),
        (Optional[Annotated[str, Constraint(nullable=True)]], None),
        (Optional[str], None),
        (Optional[str | int], None),
        (Optional[Literal["1", "2"]], None),
        (Optional[Annotated[str, "meta"]], None),
        *(
            (
                Optional[
                    str
                    | list[str]
                    | Annotated[list[int], Constraint(min_len=2)]
                    | Annotated[list[Annotated[list[int], Constraint(min_len=2)]], Constraint(min_len=1)]
                ],
                v,
            )
            for v in (None, "foo", ["foo"], [123, 456], [[123, 456]])
        ),
    ],
    indirect=["NewParamModel"],
)
def test_pydantic_model_conversion_and_validation(NewParamModel: type[ParamModel], input_value: Any) -> None:
    """Verify that Pydantic model conversion and Pydantic validation with correct input value type works"""
    field = next(iter(NewParamModel.__dataclass_fields__.values()))
    pydantic_model = NewParamModel.to_pydantic()
    assert issubclass(pydantic_model, PydanticModel)
    validated_model = pydantic_model.validate_as_json({field.name: input_value})
    assert isinstance(validated_model, PydanticModel)


@pytest.mark.parametrize(
    ("NewParamModel", "input_value"),
    [
        (str, 123),
        (str | int, 1.23),
        (Optional[str], 123),
        (Literal["1", "2"], "3"),
        (Annotated[str, "meta"], 123),
        (Annotated[str, Constraint(pattern=r"^test\d+$")], "mytest123"),
        (
            Annotated[str, Constraint(pattern=r"^test\d+$")] | Annotated[str, Constraint(pattern=r"^\d+test$")],
            "mytest123",
        ),
        (Annotated[str, Constraint(min_len=5)], "test"),
        (Annotated[str, Constraint(min_len=5)] | Annotated[int, Constraint(min=5)], "test"),
        (Annotated[str, Constraint(min_len=5)] | Annotated[int, Constraint(min=5)], 2),
        (Annotated[list[str], "meta"], [1, "foo"]),
        (Annotated[list[str], Constraint(min_len=5)], ["foo", "bar"]),
        (Optional[Literal["1", "2"]], "3"),
        (str, None),
        (Literal["1", "2"], None),
        (Annotated[str, "meta"], None),
        *(
            (
                Optional[
                    str
                    | list[str]
                    | Annotated[list[int], Constraint(min_len=2)]
                    | Annotated[list[Annotated[list[int], Constraint(min_len=2)]], Constraint(min_len=3)]
                ],
                v,
            )
            for v in (123, [123, None], [123], [[123], [456], [789]], [[1, 2], [3, 4]])
        ),
    ],
    indirect=["NewParamModel"],
)
def test_pydantic_model_conversion_and_validation_error(NewParamModel: type[ParamModel], input_value: Any) -> None:
    """Verify that Pydantic model conversion and Pydantic validation with incorrect input value type works"""
    field = next(iter(NewParamModel.__dataclass_fields__.values()))
    pydantic_model = NewParamModel.to_pydantic()
    assert issubclass(pydantic_model, PydanticModel)
    is_union = any(
        param_type_util.is_union_type(t, exclude_optional=True)
        for t in [field.type, param_type_util.get_base_type(field.type)]
    )
    expected_error = rf"\d* validation error{'s' if is_union else ''} for {pydantic_model.__name__}\n"
    with pytest.raises(ValidationError, match=expected_error):
        pydantic_model.validate_as_json({field.name: input_value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("uuid", UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"), id="uuid"),
        pytest.param("date_time", datetime.datetime(2025, 1, 1, 0, 0, 0, 000000), id="datetime"),
        pytest.param("date", datetime.date(2025, 1, 1), id="date"),
        pytest.param("time", datetime.time(1), id="time"),
        pytest.param("duration", datetime.timedelta(days=-1), id="duration"),
        pytest.param("binary", b"\x01\x02\x03\x04", id="binary"),
        pytest.param("file", lazy_fixture("image_file"), id="file"),
        pytest.param("byte", b"test", id="byte"),
        pytest.param("path", Path(__file__), id="path"),
        pytest.param("base64", base64.b64encode(b"test").decode("utf-8"), id="base64"),
        pytest.param("base64url", base64.urlsafe_b64encode(b"https://example.com").decode("utf-8"), id="base64url"),
        pytest.param("email", "me@example.com", id="email"),
        pytest.param("name_email", "foo.bar@example.com", id="name-email"),
        pytest.param("uri", "https://example.com", id="uri"),
        pytest.param("ipv4", "192.168.1.1", id="ipv4"),
        pytest.param("ipv6", "2001:0000::1", id="ipv6"),
        pytest.param("ipvanyaddress", "192.168.1.1", id="ipvanyaddress_v4"),
        pytest.param("ipvanyaddress", "2001::1", id="ipvanyaddress_v6"),
        pytest.param("ipvanyinterface", "192.168.1.0/30", id="ipvanyinterface"),
        pytest.param("ipvanyinterface", "2001::/64", id="ipvanyinterface_v6"),
        pytest.param("ipvanynetwork", "192.168.1.0/24", id="ipvanynetwork_v4"),
        pytest.param("ipvanynetwork", "2001::/64", id="ipvanynetwork_v6"),
        pytest.param("phone", "+1-650-253-0000", id="phone"),
    ],
)
def test_pydantic_model_conversion_with_annotated_format(
    ParamModelWithParamFormats: type[ParamModel], field_name: str, value: Any
) -> None:
    """Verify that Pydantic model conversion with annotated param format metadata works as expected"""
    pydantic_model = ParamModelWithParamFormats.to_pydantic()
    assert issubclass(pydantic_model, PydanticModel)
    assert field_name in pydantic_model.model_fields
    pydantic_model.validate_as_json({field_name: value})
