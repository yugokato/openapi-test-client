from typing import TYPE_CHECKING, TypeVar

from openapi_test_client.clients.base import OpenAPIClient

if TYPE_CHECKING:
    APIClientType = TypeVar("APIClientType", bound=OpenAPIClient)
