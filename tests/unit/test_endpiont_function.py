import pytest
from pytest_subtests import SubTests

from openapi_test_client.clients.demo_app.api.auth import AuthAPI
from openapi_test_client.libraries.api import Endpoint, EndpointFunc
from openapi_test_client.libraries.api.types import EndpointModel, PydanticModel

pytestmark = [pytest.mark.unittest]


def test_api_endpoint_function(subtests: SubTests, api_class_or_instance: AuthAPI | type[AuthAPI]) -> None:
    """Verify the basic capability around EndpointFunction"""
    with subtests.test("Endpoint Function"):
        assert isinstance(api_class_or_instance.login, EndpointFunc)
        assert type(api_class_or_instance.login).__name__ == "AuthAPILoginEndpointFunc"

    with subtests.test("Endpoint Object"):
        endpoint_obj = api_class_or_instance.login.endpoint
        expected_method = "post"
        expected_path = "/v1/auth/login"
        assert isinstance(endpoint_obj, Endpoint)
        assert endpoint_obj.api_class is AuthAPI
        assert endpoint_obj.method == expected_method
        assert endpoint_obj.path == expected_path
        assert endpoint_obj.func_name == "login"
        assert str(endpoint_obj) == f"{expected_method.upper()} {expected_path}"
        assert endpoint_obj.content_type is None
        if api_class_or_instance is AuthAPI:
            assert endpoint_obj.url is None
        else:
            assert endpoint_obj.url == f"{api_class_or_instance.rest_client.base_url}{expected_path}"
        assert endpoint_obj.is_public is True
        assert endpoint_obj.is_documented is True
        assert endpoint_obj.is_deprecated is False

    with subtests.test("Endpoint Model"):
        expected_model_name = "AuthAPILoginEndpointModel"
        endpoint_model = endpoint_obj.model
        assert issubclass(endpoint_model, EndpointModel)
        assert endpoint_model.__name__ == expected_model_name

        pydantic_model = endpoint_model.to_pydantic()
        assert issubclass(pydantic_model, PydanticModel)
        assert pydantic_model.__name__ == expected_model_name + "Pydantic"
