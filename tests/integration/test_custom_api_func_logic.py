from contextlib import nullcontext

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.clients.demo_app import DemoAppAPIClient

pytestmark = [pytest.mark.integrationtest, pytest.mark.xdist_group("integration/api")]


@pytest.mark.parametrize("some_id", [0, 1])
def test_custom_function_logic(unauthenticated_api_client: DemoAppAPIClient, some_id: int) -> None:
    """Test that custom endpoint function logic is handled properly.
    The logic is hard coded in the test API function of the demo app client
    """
    with (
        pytest.raises(RuntimeError, match="Custom endpoint must return a RestResponse object")
        if some_id % 2
        else nullcontext()
    ):
        r = unauthenticated_api_client._Test.test(some_id)

    if some_id % 2 == 0:
        assert isinstance(r, RestResponse)
        assert r.ok
        assert r.response == some_id * 2
