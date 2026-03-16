from dataclasses import asdict
from typing import Any

import pytest
from pytest import Subtests

from openapi_test_client.libraries.core.endpoints.utils.pydantic_model import in_validation_mode
from openapi_test_client.libraries.core.types import ParamModel, PydanticModel, Unset

pytestmark = [pytest.mark.unittest]


class TestParamModel:
    """Tests for ParamModel functionality"""

    @pytest.mark.parametrize("scenario", ["empty_model", "with_no_fields", "with_partial_fields", "with_all_fields"])
    def test_param_model(
        self,
        subtests: Subtests,
        scenario: str,
        EmptyParamModel: type[ParamModel],
        RegularParamModel: type[ParamModel],
        InnerParamModel: type[ParamModel],
    ) -> None:
        """Test that the following ParamModel capabilities work correctly:

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
            - Update a field value (as dataclass, as dictionary)
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

        model = self._do_test_instantiate_model(model_class, model_params)
        for scope in ["dataclass", "dictionary"]:
            with subtests.test(f"Add field ({scope})"):
                self._do_test_add_field(model, model_class, model_params, scope)
            with subtests.test(f"Update field ({scope})"):
                self._do_test_update_field(model, model_class, model_params, scope)
            with subtests.test(f"Delete field ({scope})"):
                self._do_test_delete_field(model, model_class, model_params, scope)

    def test_param_model_nested(
        self, subtests: Subtests, RegularParamModel: type[ParamModel], InnerParamModel: type[ParamModel]
    ) -> None:
        """Test that ParamModel functionality also works with nested param models"""
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
                self._check_model(model.param3, InnerParamModel)
                self._check_dataclass_and_dictionary_sync(model, model_params)

            with subtests.test(f"Update field ({scope})"):
                if scope == "dataclass":
                    model.param3.inner_param1 = new_value
                else:
                    model["param3"]["inner_param1"] = new_value
                self._check_model(model.param3, InnerParamModel)
                self._check_dataclass_and_dictionary_sync(model, model_params)

            with subtests.test(f"Delete field ({scope})"):
                if scope == "dataclass":
                    delattr(model.param3, "inner_param2")
                else:
                    del model["param3"]["inner_param2"]
                self._check_model(model.param3, InnerParamModel)
                self._check_dataclass_and_dictionary_sync(model, model_params)

    @pytest.mark.parametrize("validation_timing", ["create", "update"])
    def test_param_model_in_validation_mode(
        self, RegularParamModel: type[ParamModel], InnerParamModel: type[ParamModel], validation_timing: str
    ) -> None:
        """Test that Pydantic validation works in validation mode at model instantiation and field update timings"""
        with in_validation_mode():
            if validation_timing == "create":
                invalid_model_params = {"param1": 1, "param2": 2, "param3": 3, "undefined_param1": 4}
                with pytest.raises(ValueError) as e:
                    RegularParamModel(**invalid_model_params)
                print(e.value)  # noqa: T201
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
                print(e.value)  # noqa: T201
                assert f"1 validation error for {RegularParamModel.__name__}" in str(e.value)

    def _do_test_instantiate_model(
        self, model_class: type[ParamModel], model_params: dict[str, Any]
    ) -> ParamModel | PydanticModel:
        should_be_recreated = set(model_class.__dataclass_fields__.keys()) != set(model_params.keys())
        model = model_class(**model_params)
        assert sorted(model.__dataclass_fields__.keys()) == sorted(model_params.keys())
        assert dict(model) == asdict(model) == model_params
        self._check_model(model, model_class, should_be_recreated=should_be_recreated)
        self._check_dataclass_and_dictionary_sync(model, model_params)
        return model

    def _do_test_add_field(
        self,
        model: ParamModel,
        model_class: type[ParamModel],
        model_params: dict[str, Any],
        scope: str,
        field_name: str | None = None,
        field_value: Any = None,
    ) -> None:
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
        self._check_model(model, model_class)
        self._check_dataclass_and_dictionary_sync(model, model_params)

    def _do_test_update_field(
        self,
        model: ParamModel,
        model_class: type[ParamModel],
        model_params: dict[str, Any],
        scope: str,
        field_name: str | None = None,
        field_value: Any = None,
    ) -> None:
        if field_name:
            assert field_name in model.__dataclass_fields__.keys()
        else:
            field_name = next(iter(model_params.keys()))
        if not field_value:
            field_value = f"updated_value_{scope}"
        model_params[field_name] = field_value
        if scope == "dataclass":
            setattr(model, field_name, field_value)
        else:
            model[field_name] = field_value
        self._check_model(model, model_class)
        self._check_dataclass_and_dictionary_sync(model, model_params)

    def _do_test_delete_field(
        self,
        model: ParamModel,
        model_class: type[ParamModel],
        model_params: dict[str, Any],
        scope: str,
        field_name: str | None = None,
    ) -> None:
        if field_name:
            assert field_name in model.__dataclass_fields__.keys()
        else:
            field_name = next(iter(model_params.keys()))
        del model_params[field_name]
        if scope == "dataclass":
            delattr(model, field_name)
        else:
            del model[field_name]
        self._check_model(model, model_class)
        self._check_dataclass_and_dictionary_sync(model, model_params)

    def _check_model(
        self, model_obj: ParamModel, model_class: type[ParamModel], should_be_recreated: bool = True
    ) -> None:
        """Check the basic part of param models, especially making sure our custom __instancecheck__() implementation
        work as expected.
        """
        if should_be_recreated:
            assert getattr(model_obj, ParamModel._ORIGINAL_CLASS_ATTR_NAME) is model_class
        else:
            assert not hasattr(model_obj, ParamModel._ORIGINAL_CLASS_ATTR_NAME)
        assert isinstance(model_obj, model_class)
        assert isinstance(model_obj, ParamModel)
        assert issubclass(type(model_obj), ParamModel)

    def _check_dataclass_and_dictionary_sync(self, model_obj: ParamModel, model_params: dict[str, Any]) -> None:
        """Check dataclass and dictionary are synced"""

        def check_recursively(m: ParamModel, p: dict[str, Any]) -> None:
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

    def test_param_model_pop(self, RegularParamModel: type[ParamModel]) -> None:
        """Test pop() removes and returns the value for an existing key, returns default for missing key,
        and raises KeyError for missing key without default.
        """
        model = RegularParamModel(param1="foo", param2="bar")

        # Existing key: returns the value and removes it from both dict and dataclass sides
        value = model.pop("param1")
        assert value == "foo"
        assert "param1" not in dict(model)
        assert "param1" not in model.__dataclass_fields__

        # Missing key with default: returns default without raising
        default = "default"
        result = model.pop("nonexistent", default)
        assert result == default

        # Missing key without default: raises KeyError
        with pytest.raises(KeyError):
            model.pop("nonexistent")

    def test_param_model_update(self, RegularParamModel: type[ParamModel]) -> None:
        """Test update() syncs both dict and dataclass sides when called with other dict only,
        kwargs only, and both simultaneously.
        """
        param1_v = "foo"
        param2_v = "bar"
        param1_v_new = "foo_new"
        param2_v_new = "bar_new2"

        # other dict only
        model = RegularParamModel(param1=param1_v, param2=param2_v)
        model.update({"param1": param1_v_new})
        assert dict(model)["param1"] == param1_v_new
        assert getattr(model, "param1") == param1_v_new

        # kwargs only
        model2 = RegularParamModel(param1=param1_v, param2=param2_v)
        model2.update(param2=param2_v_new)
        assert dict(model2)["param2"] == param2_v_new
        assert getattr(model2, "param2") == param2_v_new

        # both other and kwargs simultaneously
        model3 = RegularParamModel(param1=param1_v, param2=param2_v)
        model3.update({"param1": param1_v_new}, param2=param2_v_new)
        assert dict(model3)["param1"] == param1_v_new
        assert getattr(model3, "param1") == param1_v_new
        assert dict(model3)["param2"] == param2_v_new
        assert getattr(model3, "param2") == param2_v_new

    def test_param_model_setdefault(self, RegularParamModel: type[ParamModel]) -> None:
        """Test setdefault() returns existing value without overwriting when key exists,
        and sets and returns the default when key is absent.
        """
        param1_v = "foo"
        default = "default"
        model = RegularParamModel(param1=param1_v)

        # Key already exists: returns existing value, doesn't overwrite
        key = "param1"
        result = model.setdefault(key, default)
        assert result == param1_v
        assert dict(model)[key] == param1_v
        assert getattr(model, key) == param1_v

        # Key doesn't exist: sets the key and returns default
        new_key = "new_key"
        result2 = model.setdefault(new_key, default)
        assert result2 == default
        assert dict(model)[new_key] == default
        assert getattr(model, new_key) == default

    def test_param_model_clear(self, RegularParamModel: type[ParamModel]) -> None:
        """Test clear() removes all fields from both dict and dataclass sides."""
        model = RegularParamModel(param1="foo", param2="bar")
        model.clear()
        assert dict(model) == {}
        assert model.__dataclass_fields__ == {}

    def test_param_model_popitem(self, RegularParamModel: type[ParamModel]) -> None:
        """Test popitem() returns a (key, value) tuple and removes the entry from both dict and dataclass sides."""
        param1_v = "foo"
        param2_v = "bar"
        model = RegularParamModel(param1=param1_v, param2=param2_v)
        initial_length = len(dict(model))

        key, value = model.popitem()

        assert len(dict(model)) == initial_length - 1
        assert key not in dict(model)
        assert key not in model.__dataclass_fields__
        # The returned value must match what was stored
        assert value in (param1_v, param2_v)

    def test_param_model_ior(self, RegularParamModel: type[ParamModel]) -> None:
        """Test |= operator (__ior__) updates the model and syncs both dict and dataclass sides."""
        param1_v = "foo"
        param2_v = "bar"
        new_key = "foobar"

        model = RegularParamModel(param1=param1_v)
        model |= {"param2": param2_v, "new_key": new_key}

        assert dict(model)["param1"] == param1_v
        assert getattr(model, "param1") == param1_v
        assert dict(model)["param2"] == param2_v
        assert getattr(model, "param2") == param2_v
        assert dict(model)["new_key"] == new_key
        assert getattr(model, "new_key") == new_key

    def test_param_model_copy(self, RegularParamModel: type[ParamModel]) -> None:
        """Test copy() returns a new ParamModel instance with the same content but independent from the original."""
        param1_v = "foo"
        param2_v = "bar"
        model = RegularParamModel(param1=param1_v, param2=param2_v)
        copy = model.copy()

        assert isinstance(copy, ParamModel)
        assert dict(copy) == dict(model)

        # Modifying copy doesn't affect original
        copy["param1"] = "modified"
        assert dict(model)["param1"] == param1_v

        # Modifying original doesn't affect copy
        model["param2"] = "changed"
        assert dict(copy)["param2"] == param2_v

    def test_unset_repr(self) -> None:
        """Test that Unset sentinel has repr 'Unset' and bool value False."""
        assert repr(Unset) == "Unset"
        assert bool(Unset) is False
