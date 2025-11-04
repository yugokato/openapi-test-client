import pytest
from pytest_mock import MockerFixture

from openapi_test_client.clients.demo_app import DemoAppAPIClient
from openapi_test_client.libraries.api import EndpointFunc
from openapi_test_client.libraries.api.api_classes.base import APIBase
from openapi_test_client.libraries.api.api_functions.endpoints import EndpointHandler

pytestmark = [pytest.mark.unittest]


@pytest.mark.parametrize("with_instance", [True, False])
def test_endpoint_handler(mocker: MockerFixture, api_client: DemoAppAPIClient, with_instance: bool) -> None:
    """Verify the basic capability around EndpointHandler"""

    class TestAPI(APIBase):
        TAGs = ("Test",)
        app_name = api_client.app_name

        def do_something(self) -> ...:
            """A fake API function without the @endpoint.<method>(<path>) decorator"""
            ...

    mocker.patch.dict(EndpointHandler._endpoint_functions, values={}, clear=True)

    # Convert the API function to an EndpointHandler.
    # This is equivalent to applying the @endpoint.<method>(<path>) decorator
    method = "do"
    path = "/something"
    endpoint_handler = EndpointHandler(TestAPI.do_something, method=method, path=path)

    # __get__() should return an EndpointFunction obj
    instance = TestAPI(api_client) if with_instance else None
    endpoint_func = endpoint_handler.__get__(instance, TestAPI)
    assert isinstance(endpoint_func, EndpointFunc)
    assert type(endpoint_func).__name__ == "TestAPIDoSomethingEndpointFunc"
    assert endpoint_func.method == method
    assert endpoint_func.path == path
    assert endpoint_func._original_func is TestAPI.do_something

    # Check cache
    cache_key = (TestAPI.do_something.__name__, instance, TestAPI)
    assert cache_key in EndpointHandler._endpoint_functions.keys()
    assert EndpointHandler._endpoint_functions[cache_key] is endpoint_func
    endpoint_func2 = endpoint_handler.__get__(instance, TestAPI)
    assert endpoint_func is endpoint_func2
