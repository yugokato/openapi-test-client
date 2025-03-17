from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from openapi_test_client.clients.base import OpenAPIClient
from openapi_test_client.libraries.api import Endpoint, EndpointFunc
from openapi_test_client.libraries.api.api_classes.base import APIBase
from openapi_test_client.libraries.api.api_client_generator import (
    generate_api_class,
    generate_api_client,
    generate_base_api_class,
    update_endpoint_functions,
)
from openapi_test_client.libraries.api.types import ParamModel
from openapi_test_client.libraries.common.misc import reload_obj
from tests.unit import helper


def test_generate_base_api_class_code(temp_api_client: OpenAPIClient) -> None:
    """Verify code generation of new base API class works"""
    app_name = temp_api_client.app_name
    NewBaseAPIClass = generate_base_api_class(temp_api_client)
    assert issubclass(NewBaseAPIClass, APIBase)
    assert NewBaseAPIClass.__name__ == "TestAppBaseAPI"
    assert NewBaseAPIClass.__module__.endswith(f".api.base.{app_name}_api")
    assert (Path(inspect.getfile(NewBaseAPIClass)).parent / "__init__.py").exists()
    assert NewBaseAPIClass.app_name == app_name
    assert NewBaseAPIClass.endpoints is None


@pytest.mark.parametrize("add_endpoint_functions", [False, True])
def test_generate_api_class_code(
    temp_api_client: OpenAPIClient, openapi_specs: dict[str, Any], add_endpoint_functions: bool
) -> None:
    """Verify code generation of new API class works

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


@pytest.mark.parametrize("update_type", ["missing_endpoints", "target_endpoint", "ignore_endpoint", "param_model_only"])
def test_update_endpoint_function_code(
    temp_api_client: OpenAPIClient, openapi_specs: dict[str, Any], update_type: str
) -> None:
    """Verify code generation for updating endpoint functions works"""
    api_class_name = "TestSomethingAPI"

    # Generate API class without endpoint functions
    is_new_api_class = update_type == "missing_endpoints"
    NewAPIClass = do_generate_api_class(temp_api_client, api_class_name, add_endpoint_functions=not is_new_api_class)
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


def test_generate_api_client_code(temp_api_client: OpenAPIClient, mocker: MockerFixture) -> None:
    """Verify code generation of new API client works

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

    # Initializa the client and check both API classes are accessible
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


def do_generate_api_class(
    temp_api_client: OpenAPIClient,
    api_class_name: str,
    add_endpoint_functions: bool = True,
) -> type[APIBase]:
    result = generate_api_class(temp_api_client, "Test", api_class_name, add_endpoint_functions=add_endpoint_functions)
    assert not isinstance(result, tuple), "API class generation failed"
    return result
