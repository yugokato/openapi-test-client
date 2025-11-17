from contextlib import nullcontext

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.parametrize("number", [0, 1])
def test_custom_function_logic(unauthenticated_api_client: DemoAppAPIClient, number: int) -> None:
    """Test that custom endpoint function logic is handled properly.
    The logic is hard coded in the test API function of the demo app client
    """
    with (
        pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object")
        if number % 2
        else nullcontext()
    ):
        r = unauthenticated_api_client._Test.echo(number)
        assert r.ok
        assert isinstance(r, RestResponse)
        assert number % 2 == 0
        assert r.response == number * 2
