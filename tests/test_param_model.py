from dataclasses import asdict
from typing import Any, Literal

import pytest
from pytest_subtests import SubTests

from openapi_test_client.libraries.api.api_functions.utils.pydantic_model import in_validation_mode
from openapi_test_client.libraries.api.types import ParamModel


@pytest.mark.parametrize("scenario", ["empty_model", "with_no_fields", "with_partial_fields", "with_all_fields"])
def test_param_model(subtests: SubTests, scenario, EmptyParamModel, RegularParamModel, InnerParamModel):
    """Verify the functionality around the following ParamModel capabilities

    1. Model creation and dynamic recreation logic handled by ParamModel.__new__()
    2. Seamless behavior between dataclass and dictionary

    The above should work at the following two different stages:
    1. Instantiation
        Param model instantiation should work for the following scenarios:
        - An empty model with arbitrary fields (dynamic model recreation)
        - A regular model with no fields given (dynamic model recreation)
        - A regular model with partial fields given (dynamic model recreation)
        - A regular model with all fields given
    2. Modify instance (add/update/delete)
        On each object, the following operations should work. An action taken to one scope (dataclass or dictionary)
        should be automatically reflected to the other.
        - Add a new field (to dataclass, to dictionary)
        - Update an field value (as dataclass, as dictionary)
        - Delete a field (from dataclass, from dictionary)
    """
    if scenario == "empty_model":
        model_class = EmptyParamModel
        assert model_class.__dataclass_fields__ == {}
        model_params = {"undefined_param1": "foo", "undefined_param2": "bar"}
    elif scenario == "with_no_fields":
        model_class = RegularParamModel
        assert model_class.__dataclass_fields__ != {}
        model_params = {}
    elif scenario == "with_partial_fields":
        model_class = RegularParamModel
        model_params = {"param1": "123", "param2": "test"}
        assert set(model_class.__dataclass_fields__.keys()).difference(set(model_params.keys()))
    elif scenario == "with_all_fields":
        model_class = RegularParamModel
        model_params = {
            "param1": "123",
            "param2": "test",
            "param3": InnerParamModel(inner_param1="123", inner_param2="456"),
        }
        assert sorted(model_class.__dataclass_fields__.keys()) == sorted(model_params.keys())
    else:
        raise NotImplementedError(f"Invalid scenario: {scenario}")

    model = do_test_instantiate_model(model_class, model_params)
    for scope in ["dataclass", "dictionary"]:
        with subtests.test(f"Add field ({scope})"):
            do_test_add_field(model, model_class, model_params, scope)
        with subtests.test(f"Update field ({scope})"):
            do_test_update_field(model, model_class, model_params, scope)
        with subtests.test(f"Delete field ({scope})"):
            do_test_delete_field(model, model_class, model_params, scope)


def test_param_model_nested(subtests: SubTests, RegularParamModel, InnerParamModel):
    """Verify the above ParamModel functionality also works with nested param models"""
    model_params = {
        "param1": "123",
        "param2": "test",
        "param3": InnerParamModel(inner_param1="123", inner_param2="456"),
    }
    model = RegularParamModel(**model_params)
    for scope in ["dataclass", "dictionary"]:
        new_field = f"new_field_{scope}"
        new_value = f"new_field_value_{scope}"
        with subtests.test(f"Add field ({scope})"):
            if scope == "dataclass":
                assert not hasattr(model.param3, new_field)
                setattr(model.param3, new_field, new_value)
                assert hasattr(model.param3, new_field)
            else:
                assert new_field not in model["param3"]
                model["param3"][new_field] = new_value
            check_model(model.param3, InnerParamModel)
            check_dataclass_and_dictionary_sync(model, model_params)

        with subtests.test(f"Update field ({scope})"):
            if scope == "dataclass":
                model.param3.inner_param1 = new_value
            else:
                model["param3"]["inner_param1"] = new_value
            check_model(model.param3, InnerParamModel)
            check_dataclass_and_dictionary_sync(model, model_params)

        with subtests.test(f"Delete field ({scope})"):
            if scope == "dataclass":
                delattr(model.param3, "inner_param2")
            else:
                del model["param3"]["inner_param2"]
            check_model(model.param3, InnerParamModel)
            check_dataclass_and_dictionary_sync(model, model_params)


@pytest.mark.parametrize("validation_timing", ["create", "update"])
def test_param_model_validation_mode(subtests: SubTests, RegularParamModel, InnerParamModel, validation_timing):
    """Verify Pydantic validation in validation mode

    The validation should happen at the following timings:
    - Model instantiation
    - Update model field value
    """
    with in_validation_mode():
        if validation_timing == "create":
            invalid_model_params = {"param1": 1, "param2": 2, "param3": 3, "undefined_param1": 4}
            with pytest.raises(ValueError) as e:
                RegularParamModel(**invalid_model_params)
            print(e.value)
            assert f"4 validation errors for {RegularParamModel.__name__}" in str(e.value)
        else:
            valid_model_params = {
                "param1": "foo",
                "param2": "bar",
                "param3": InnerParamModel(inner_param1="foo", inner_param2="bar"),
            }
            model = RegularParamModel(**valid_model_params)
            with pytest.raises(ValueError) as e:
                model.param3.inner_param1 = 123
            print(e.value)
            assert f"1 validation error for {RegularParamModel.__name__}" in str(e.value)


def do_test_instantiate_model(model_class, model_params):
    should_be_recreated = set(model_class.__dataclass_fields__.keys()) != set(model_params.keys())
    model = model_class(**model_params)
    assert sorted(model.__dataclass_fields__.keys()) == sorted(model_params.keys())
    assert dict(model) == asdict(model) == model_params
    check_model(model, model_class, should_be_recreated=should_be_recreated)
    check_dataclass_and_dictionary_sync(model, model_params)
    return model


def do_test_add_field(
    model,
    model_class,
    model_params,
    scope: Literal["dataclass", "dictionary"],
    field_name: str = None,
    field_value: Any = None,
):
    if not field_name:
        field_name = f"new_field_{scope}"
    if not field_value:
        field_value = f"value_{scope}"
    model_params[field_name] = field_value
    if scope == "dataclass":
        assert not hasattr(model, field_name)
        setattr(model, field_name, field_value)
    else:
        assert field_name not in model
        model[field_name] = field_value
    check_model(model, model_class)
    check_dataclass_and_dictionary_sync(model, model_params)


def do_test_update_field(
    model,
    model_class,
    model_params,
    scope: Literal["dataclass", "dictionary"],
    field_name: str = None,
    field_value: Any = None,
):
    if field_name:
        assert field_name in model.__dataclass_fields__.keys()
    else:
        field_name = list(model_params.keys())[0]
    if not field_value:
        field_value = f"updated_value_{scope}"
    model_params[field_name] = field_value
    if scope == "dataclass":
        setattr(model, field_name, field_value)
    else:
        model[field_name] = field_value
    check_model(model, model_class)
    check_dataclass_and_dictionary_sync(model, model_params)


def do_test_delete_field(
    model, model_class, model_params, scope: Literal["dataclass", "dictionary"], field_name: str = None
):
    if field_name:
        assert field_name in model.__dataclass_fields__.keys()
    else:
        field_name = list(model_params.keys())[0]
    del model_params[field_name]
    if scope == "dataclas":
        delattr(model, field_name)
    else:
        del model[field_name]
    check_model(model, model_class)
    check_dataclass_and_dictionary_sync(model, model_params)


def check_model(model_obj: ParamModel, model_class: type[ParamModel], should_be_recreated: bool = True):
    """Check the basic part of param models, especially making sure our custom __instancecheck__() implementation work
    as expected.
    """
    if should_be_recreated:
        assert getattr(model_obj, ParamModel._ORIGINAL_CLASS_ATTR_NAME) is model_class
    else:
        assert not hasattr(model_obj, ParamModel._ORIGINAL_CLASS_ATTR_NAME)
    assert isinstance(model_obj, model_class)
    assert isinstance(model_obj, ParamModel)
    assert issubclass(type(model_obj), ParamModel)


def check_dataclass_and_dictionary_sync(model_obj: ParamModel, model_params: dict[str, Any]):
    """Check dataclass and dictionary are synced"""

    def check_recursively(m: ParamModel, p: dict[str, Any]):
        assert sorted(m.__dataclass_fields__.keys()) == sorted(p.keys())
        assert dict(m) == p
        assert asdict(m) == p
        for field_name in m.__dataclass_fields__.keys():
            field_value = getattr(m, field_name)
            param_value = p[field_name]
            assert field_value == param_value
            if isinstance(field_value, ParamModel):
                check_recursively(field_value, param_value)

    check_recursively(model_obj, model_params)
