from openapi_test_client.libraries.endpoints.endpoint import Endpoint
from openapi_test_client.libraries.endpoints.endpoint_factory import endpoint
from openapi_test_client.libraries.endpoints.endpoint_func import AsyncEndpointFunc, EndpointFunc, SyncEndpointFunc
from openapi_test_client.libraries.endpoints.endpoint_handler import EndpointHandler

# Code gen derives the generated import path from endpoint.__module__. Point it at this facade so generated clients
# import from here.
endpoint.__module__ = __name__

__all__ = ["AsyncEndpointFunc", "Endpoint", "EndpointFunc", "EndpointHandler", "SyncEndpointFunc", "endpoint"]
