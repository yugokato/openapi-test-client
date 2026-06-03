from __future__ import annotations

import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import NoneType
from typing import Annotated, Any, ForwardRef, Literal, get_args, get_origin

import pytest
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core.base import APIBase
from openapi_test_client.libraries.core.base.api_class import get_api_classes
from openapi_test_client.libraries.openapi import Endpoint, EndpointFunc
from openapi_test_client.libraries.openapi.base.api_client import OpenAPIClient
from openapi_test_client.libraries.openapi.code_gen import utils
from openapi_test_client.libraries.openapi.code_gen.client_generator import (
    generate_api_class,
    generate_api_client,
    generate_base_api_class,
    update_endpoint_functions,
)
from openapi_test_client.libraries.openapi.types import (
    Alias,
    Constraint,
    Format,
    Optional,
    ParamModel,
    Query,
    UncacheableLiteralArg,
    Unset,
)
from openapi_test_client.libraries.openapi.utils.modules import (
    get_module_name_by_file_path,
    import_module_with_new_code,
    reload_obj,
)
from tests.unit.tests_code_gen import helper

pytestmark = [pytest.mark.unittest]


class TestGenerateBaseApiClass:
    """Tests for generate_base_api_class()"""

    def test_generate_base_api_class_code(self, temp_api_client: OpenAPIClient) -> None:
        """Test that code generation of new base API class works"""
        app_name = temp_api_client.app_name
        NewBaseAPIClass = generate_base_api_class(temp_api_client)
        assert issubclass(NewBaseAPIClass, APIBase)
        assert NewBaseAPIClass.__name__ == "TestAppBaseAPI"
        assert NewBaseAPIClass.__module__.endswith(f".api.base.{app_name}_api")
        assert (Path(inspect.getfile(NewBaseAPIClass)).parent / "__init__.py").exists()
        assert NewBaseAPIClass.app_name == app_name
        assert NewBaseAPIClass.endpoints is None


class TestGenerateApiClass:
    """Tests for generate_api_class()"""

    @pytest.mark.parametrize("add_endpoint_functions", [False, True])
    def test_generate_api_class_code(
        self, temp_api_client: OpenAPIClient, openapi_specs: dict[str, Any], add_endpoint_functions: bool
    ) -> None:
        """Test that code generation of new API class works

        When add_endpoint_functions option is given, the API class code should include associated API functions and
        param models as well
        """
        api_class_name = "TestSomethingAPI"
        NewAPIClass = do_generate_api_class(
            temp_api_client,
            api_class_name,
            add_endpoint_functions=add_endpoint_functions,
        )
        assert issubclass(NewAPIClass, APIBase)
        assert NewAPIClass.__bases__[0].__name__ == "TestAppBaseAPI"
        assert NewAPIClass.__name__ == api_class_name
        assert NewAPIClass.__module__.endswith(".test_something")
        assert NewAPIClass.app_name == temp_api_client.app_name
        assert NewAPIClass.TAGs == ("Test",)
        assert (Path(inspect.getfile(NewAPIClass)).parent / "__init__.py").exists()
        # API class generation will trigger the initialization of API classes, which will update the `endpoints` attr
        assert NewAPIClass.endpoints is not None
        if add_endpoint_functions:
            assert len(NewAPIClass.endpoints) > 0
            assert all(isinstance(e, Endpoint) for e in NewAPIClass.endpoints)
        else:
            assert NewAPIClass.endpoints == []

        # Check models
        mod = inspect.getmodule(NewAPIClass)
        Metadata = getattr(mod, "Metadata", None)
        if add_endpoint_functions:
            assert Metadata and issubclass(Metadata, ParamModel)
        else:
            assert Metadata is None

        # Check API functions
        num_available_endpoints = len(helper.get_defined_endpoints(openapi_specs))
        for i in range(num_available_endpoints):
            api_func_name = f"_unnamed_endpoint_{i + 1}"
            api_func = getattr(NewAPIClass, api_func_name, None)
            if add_endpoint_functions:
                assert api_func
                assert isinstance(api_func, EndpointFunc)
            else:
                assert not api_func


class TestUpdateEndpointFunction:
    """Tests for update_endpoint_functions()"""

    @pytest.mark.parametrize(
        "update_type", ["missing_endpoints", "target_endpoint", "ignore_endpoint", "param_model_only"]
    )
    def test_update_endpoint_function_code(
        self, temp_api_client: OpenAPIClient, openapi_specs: dict[str, Any], update_type: str
    ) -> None:
        """Test that code generation for updating endpoint functions works"""
        api_class_name = "TestSomethingAPI"

        # Generate API class without endpoint functions
        is_new_api_class = update_type == "missing_endpoints"
        NewAPIClass = do_generate_api_class(
            temp_api_client, api_class_name, add_endpoint_functions=not is_new_api_class
        )
        first_endpoint = helper.get_defined_endpoints(openapi_specs)[0]
        target_endpoints = None
        endpoints_to_ignore = None
        update_param_models_only = False
        add_missing_endpoints = False

        if update_type == "missing_endpoints":
            add_missing_endpoints = True
        elif update_type == "target_endpoint":
            target_endpoints = [first_endpoint]
        elif update_type == "ignore_endpoint":
            endpoints_to_ignore = [first_endpoint]
        elif update_type == "param_model_only":
            update_param_models_only = True
        else:
            raise NotImplementedError(f"Invalid update_type: {update_type}")

        # Modify the OpenAPI specs to simulate some updates around endpoints
        # We will add a new parameter to all endpoints, and delete one parameter from the Metadata model
        endpoint_param_to_add = "new_param"
        model_param_to_delete = "additional_info"
        updated_openapi_specs = helper.generate_updated_specs(
            openapi_specs, endpoint_param_to_add=endpoint_param_to_add, model_param_to_delete=model_param_to_delete
        )

        # Do update
        result = update_endpoint_functions(
            NewAPIClass,
            updated_openapi_specs,
            is_new_api_class=is_new_api_class,
            target_endpoints=target_endpoints,
            endpoints_to_ignore=endpoints_to_ignore,
            add_missing_endpoints=add_missing_endpoints,
            update_param_models_only=update_param_models_only,
        )
        assert result is True

        # Reload the module to reflect the updated code
        UpdatedNewAPIClass = reload_obj(NewAPIClass)

        # Check all API functions defined exist in the code
        num_available_endpoints = len(helper.get_defined_endpoints(updated_openapi_specs))
        for i in range(num_available_endpoints):
            api_func_name = f"_unnamed_endpoint_{i + 1}"
            assert hasattr(UpdatedNewAPIClass, api_func_name)

        # Check Metadata model exists
        mod = inspect.getmodule(UpdatedNewAPIClass)
        assert hasattr(mod, "Metadata")
        Metadata: ParamModel = reload_obj(mod.Metadata)

        # Check new API function signatures and the Metadata model change
        sig_endpoint1 = inspect.signature(UpdatedNewAPIClass._unnamed_endpoint_1)
        sig_endpoint2 = inspect.signature(UpdatedNewAPIClass._unnamed_endpoint_2)
        sig_endpoint3 = inspect.signature(UpdatedNewAPIClass._unnamed_endpoint_3)
        if update_type == "missing_endpoints":
            assert endpoint_param_to_add in sig_endpoint1.parameters
            assert endpoint_param_to_add in sig_endpoint2.parameters
            assert endpoint_param_to_add in sig_endpoint3.parameters
            assert model_param_to_delete not in Metadata.__dataclass_fields__
        elif update_type == "target_endpoint":
            # Only the first endpoint should be updated
            assert endpoint_param_to_add in sig_endpoint1.parameters
            assert endpoint_param_to_add not in sig_endpoint2.parameters
            assert endpoint_param_to_add not in sig_endpoint3.parameters
            assert model_param_to_delete not in Metadata.__dataclass_fields__
        elif update_type == "ignore_endpoint":
            # The first endpoint should not be updated
            assert endpoint_param_to_add not in sig_endpoint1.parameters
            assert endpoint_param_to_add in sig_endpoint2.parameters
            assert endpoint_param_to_add in sig_endpoint3.parameters
            assert model_param_to_delete in Metadata.__dataclass_fields__
        else:
            assert endpoint_param_to_add not in sig_endpoint1.parameters
            assert endpoint_param_to_add not in sig_endpoint2.parameters
            assert endpoint_param_to_add not in sig_endpoint3.parameters
            assert model_param_to_delete not in Metadata.__dataclass_fields__

    def test_update_endpoint_function_when_decorator_below_endpoint_decorator(
        self, temp_api_client: OpenAPIClient, openapi_specs: dict[str, Any]
    ) -> None:
        """Test that update_endpoint_functions() picks up endpoints where a decorator is placed below
        @endpoint.<method>()"""
        api_class_name = "TestSomethingAPI"
        NewAPIClass = do_generate_api_class(temp_api_client, api_class_name, add_endpoint_functions=True)

        # Generated code places @endpoint.is_public above @endpoint.<method>(). Swap the order so the
        # flag decorator sits below @endpoint.<method>() to exercise the new position-independent style.
        api_cls_file_path = Path(inspect.getfile(NewAPIClass))
        original_code = api_cls_file_path.read_text()
        reordered_code = re.sub(
            r"(    @endpoint\.is_public\n)(    @endpoint\.\w+\([^\n]*\)\n)",
            r"\2\1",
            original_code,
        )
        assert reordered_code != original_code, (
            "Reorder failed: expected @endpoint.is_public above @endpoint.<method>()"
        )
        api_cls_file_path.write_text(reordered_code)

        # Update with new params added to all endpoints
        endpoint_param_to_add = "new_param"
        updated_openapi_specs = helper.generate_updated_specs(
            openapi_specs, endpoint_param_to_add=endpoint_param_to_add, model_param_to_delete="additional_info"
        )
        result = update_endpoint_functions(NewAPIClass, updated_openapi_specs, add_missing_endpoints=False)
        assert result is True

        # The endpoint must have been matched and its signature updated, not silently skipped
        UpdatedNewAPIClass = reload_obj(NewAPIClass)
        sig = inspect.signature(UpdatedNewAPIClass._unnamed_endpoint_1)
        assert endpoint_param_to_add in sig.parameters

        # The below-decorator must be preserved without duplication (3 endpoints → 3 occurrences)
        updated_code = api_cls_file_path.read_text()
        assert updated_code.count("@endpoint.is_public") == 3


class TestGenerateApiClient:
    """Tests for generate_api_client()"""

    def test_generate_api_client_code(self, temp_api_client: OpenAPIClient, mocker: MockerFixture) -> None:
        """Test that code generation of new API client works

        NOTE: This test requires at least one API class generation to be done first
        """
        # Generate 2 API classes
        NewAPIClass1 = do_generate_api_class(temp_api_client, "TestSomething1API")
        NewAPIClass2 = do_generate_api_class(temp_api_client, "TestSomething2API")

        # Generate API client
        NewAPIClient = generate_api_client(temp_api_client)
        assert issubclass(NewAPIClient, OpenAPIClient)
        assert NewAPIClient.__name__ == "TestAppAPIClient"
        assert (Path(inspect.getfile(NewAPIClient)).parent / "__init__.py").exists()

        # Initialize the client and check both API classes are accessible
        api_client = NewAPIClient()
        assert api_client.app_name == temp_api_client.app_name
        assert hasattr(api_client, "TestSomething1")
        assert hasattr(api_client, "TestSomething2")
        assert isinstance(api_client.TestSomething1, NewAPIClass1)
        assert isinstance(api_client.TestSomething2, NewAPIClass2)

        # Make an API request using a mocked RestAPI client function call
        rest_client = api_client.rest_client
        assert hasattr(NewAPIClass1, "_unnamed_endpoint_1")
        mock = mocker.patch(
            f"{rest_client.__module__}.{type(rest_client).__name__}._{NewAPIClass1._unnamed_endpoint_1.method}"
        )
        api_client.TestSomething1._unnamed_endpoint_1()
        mock.assert_called_once()

    def test_generate_api_client_code_has_no_duplicate_accessors(self, temp_api_client: OpenAPIClient) -> None:
        """Test that the generated API client class contains exactly one @cached_property accessor per API class."""
        do_generate_api_class(temp_api_client, "TestSomething1API")
        do_generate_api_class(temp_api_client, "TestSomething2API")

        NewAPIClient = generate_api_client(temp_api_client)
        client_file_path = Path(inspect.getfile(NewAPIClient))
        client_code = client_file_path.read_text()

        # The number of @cached_property decorators must equal the number of generated API classes (2)
        cached_property_count = client_code.count("@cached_property")
        assert cached_property_count == 2, (
            f"Expected 2 @cached_property accessors in the generated client, found {cached_property_count}.\n"
            f"Generated code:\n{client_code}"
        )

        # Each accessor name must appear exactly once
        for accessor_name in ["TestSomething1", "TestSomething2"]:
            accessor_occurrences = client_code.count(f"def {accessor_name}(self)")
            assert accessor_occurrences == 1, (
                f"Accessor '{accessor_name}' appears {accessor_occurrences} times (expected 1).\n"
                f"Generated code:\n{client_code}"
            )


class TestGetApiClasses:
    """Tests for get_api_classes()"""

    def test_get_api_classes_deduplicates_stale_reload_artifacts(self, temp_api_client: OpenAPIClient) -> None:
        """Test that get_api_classes() returns each API class exactly once even when stale class objects
        from module reloads remain reachable via __subclasses__().
        """
        NewAPIClass = do_generate_api_class(temp_api_client, "TestSomethingAPI")

        # Simulate a reload: exec the same source into the existing module, which defines a second
        # class object with the same name. Keep a reference to the original so GC cannot collect it.
        api_class_file_path = Path(inspect.getfile(NewAPIClass))
        source = api_class_file_path.read_text()
        stale_class = NewAPIClass  # prevent garbage collection
        import_module_with_new_code(source, api_class_file_path)

        # The stale class and the live class must now be distinct objects with the same __name__
        live_class = getattr(sys.modules[NewAPIClass.__module__], NewAPIClass.__name__)
        assert stale_class is not live_class, "Expected stale and live class to be different objects after reload"

        # get_api_classes() must return exactly one entry per class name (the live one)
        api_module_name = get_module_name_by_file_path(api_class_file_path.parent / "__init__.py").removesuffix(
            ".__init__"
        )
        base_class = NewAPIClass.__bases__[0]
        result = get_api_classes(api_module_name, base_class)

        class_names = [cls.__name__ for cls in result]
        assert class_names.count(NewAPIClass.__name__) == 1, (
            f"get_api_classes() returned {class_names.count(NewAPIClass.__name__)} copies of "
            f"'{NewAPIClass.__name__}' (expected 1). Full result: {class_names}"
        )
        # The returned class must be the live one, not a stale reload artifact
        returned_class = next(cls for cls in result if cls.__name__ == NewAPIClass.__name__)
        assert returned_class is live_class, (
            "get_api_classes() returned the stale class object instead of the current live one"
        )


class TestCodeGenUtils:
    """Tests for code_gen utils"""

    class MyClass: ...

    @dataclass
    class MyParamModel(ParamModel):
        param1: str = Unset
        param2: str = Unset

    @pytest.mark.parametrize("as_list", [False, True])
    @pytest.mark.parametrize("is_optional", [False, True])
    @pytest.mark.parametrize(
        ("tp", "expected_tp_code"),
        [
            (None, "None"),
            (NoneType, "None"),
            (Any, "Any"),
            (str, "str"),
            (int, "int"),
            (bool, "bool"),
            (list, "list"),
            (dict, "dict"),
            (dict[str, Any], "dict[str, Any]"),
            (Literal[None], "Literal[None]"),
            (Literal[UncacheableLiteralArg(None)], "Literal[None]"),
            (Literal["1", "2"], "Literal['1', '2']"),
            (Literal[UncacheableLiteralArg("1"), UncacheableLiteralArg("2")], "Literal['1', '2']"),
            (MyClass, MyClass.__name__),
            (MyParamModel, MyParamModel.__name__),
            (ForwardRef(MyParamModel.__name__), MyParamModel.__name__),
            # Union/Optional
            (str | int, "str | int"),
            (dict[str, Any] | MyParamModel, f"dict[str, Any] | {MyParamModel.__name__}"),
            (int | None, "Optional[int]"),
            (int | None | MyParamModel, f"Optional[int | {MyParamModel.__name__}]"),
            # Annotated
            (Annotated[str, "meta"], "Annotated[str, 'meta']"),
            (Annotated[str, Query()], "Annotated[str, Query()]"),
            (
                Annotated[str, "meta1", "meta2", Format(value="uuid"), Alias("foo"), Constraint(min=1)],
                "Annotated[str, 'meta1', 'meta2', Format('uuid'), Alias('foo'), Constraint(min=1)]",
            ),
            (
                Annotated[str, "meta", Constraint(pattern=r"^[A-Z]+$")],
                "Annotated[str, 'meta', Constraint(pattern=r'^[A-Z]+$')]",
            ),
            (Annotated[str | int, "meta"], "Annotated[str | int, 'meta']"),
        ],
    )
    def test_generate_type_annotation_code(
        self, tp: Any, expected_tp_code: str, is_optional: bool, as_list: bool
    ) -> None:
        """Test that a string version of type annotation can be generated from various annotated types"""
        if (tp in [NoneType, None] or isinstance(tp, str)) and (is_optional or as_list):
            pytest.skip("Not applicable")

        if as_list:
            if get_origin(tp) is Annotated:
                inner_type = get_args(tp)[0]
                tp = Annotated[list[inner_type], *tp.__metadata__]  # type: ignore[valid-type]
                expected_tp_code = re.sub(r"Annotated\[([^,]+)", r"Annotated[list[\1]", expected_tp_code)
            else:
                tp = list[tp]
                expected_tp_code = f"list[{expected_tp_code}]"
        if is_optional and not expected_tp_code.startswith("Optional["):
            tp = Optional[tp]
            expected_tp_code = f"Optional[{expected_tp_code}]"

        assert utils.generate_type_annotation_code(tp) == expected_tp_code


class TestGenerateImportsCode:
    """Tests for generate_imports_code_from_model() — verifying split-package import paths"""

    def test_unset_import_uses_openapi_types_module(self, temp_api_client: OpenAPIClient) -> None:
        """Test that a model with Unset defaults emits 'from openapi_test_client.libraries.openapi.types import Unset'

        This asserts the split-package contract: generated code must import Unset from the openapi layer,
        not from core.types, so that a future removal of the core re-export does not silently break clients.
        """
        from dataclasses import make_dataclass

        import openapi_test_client.libraries.openapi.types as openapi_types_module

        # Use make_dataclass to avoid from __future__ import annotations stringifying the field type
        UnsetModel = make_dataclass("UnsetModel", [("field1", str, Unset)], bases=(ParamModel,))

        NewAPIClass = do_generate_api_class(temp_api_client, "TestSomethingAPI", add_endpoint_functions=True)
        imports_code = utils.generate_imports_code_from_model(NewAPIClass, UnsetModel)

        expected = f"from {openapi_types_module.__name__} import Unset"
        assert expected in imports_code, (
            f"Expected Unset import from openapi types module.\n"
            f"Expected line: {expected!r}\n"
            f"Actual imports_code:\n{imports_code}"
        )
        assert "from openapi_test_client.libraries.core.types import Unset" not in imports_code

    def test_optional_import_uses_openapi_types_module(self, temp_api_client: OpenAPIClient) -> None:
        """Test that a model with Optional fields emits
        'from openapi_test_client.libraries.openapi.types import Optional'.

        Mirrors the Unset contract: Optional is an openapi-layer alias and must be imported from there.
        """
        from dataclasses import make_dataclass

        import openapi_test_client.libraries.openapi.types as openapi_types_module

        # Use make_dataclass to avoid from __future__ import annotations stringifying the field type
        OptionalModel = make_dataclass(
            "OptionalModel", [("field1", openapi_types_module.Optional[str], Unset)], bases=(ParamModel,)
        )

        NewAPIClass = do_generate_api_class(temp_api_client, "TestSomethingAPI", add_endpoint_functions=True)
        imports_code = utils.generate_imports_code_from_model(NewAPIClass, OptionalModel)

        expected = f"from {openapi_types_module.__name__} import Optional"
        assert expected in imports_code, (
            f"Expected Optional import from openapi types module.\n"
            f"Expected line: {expected!r}\n"
            f"Actual imports_code:\n{imports_code}"
        )
        assert "from typing import Optional" not in imports_code


def do_generate_api_class(
    temp_api_client: OpenAPIClient,
    api_class_name: str,
    add_endpoint_functions: bool = True,
) -> type[APIBase]:
    result = generate_api_class(temp_api_client, "Test", api_class_name, add_endpoint_functions=add_endpoint_functions)
    assert not isinstance(result, tuple), "API class generation failed"
    return result
