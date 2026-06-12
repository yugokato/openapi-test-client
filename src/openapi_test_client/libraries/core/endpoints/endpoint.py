from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, ParamSpec

from ..types import EndpointModel, RestResponse

if TYPE_CHECKING:
    from ..base.api_class import APIBase, APIClientT

P = ParamSpec("P")

__all__ = ["Endpoint"]


@dataclass(frozen=True, slots=True)
class Endpoint(Generic[P]):
    """An Endpoint class to hold various endpoint data associated to an API class function

    This is accessible via an EndpointFunc object (see docstrings of the `endpoint` class below).
    """

    api_class: type[APIBase[Any]]
    method: str
    path: str
    func_name: str
    model: type[EndpointModel]
    url: str | None = None  # Available only for an endpoint object accessed via an API client instance
    content_type: str | None = None
    is_public: bool = False
    is_documented: bool = True
    is_deprecated: bool = False

    def __str__(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def __eq__(self, obj: Any) -> bool:
        return isinstance(obj, Endpoint) and self.api_class is obj.api_class and str(self) == str(obj)

    def __hash__(self) -> int:
        return hash((self.api_class, str(self)))

    def __call__(self, api_client: APIClientT, *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint using the given API client

        NOTE: If the provided API client is in async mode, the returned value is a coroutine that needs be awaited by
        the caller

        Parameters can be passed either positionally or as keyword arguments — same flexible convention as calling
        the endpoint function directly (see EndpointFunc.__call__).

        :param api_client: API client to use for the call
        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)

        Example:
            >>> from myproject.clients.my_app.my_app_client import MyAppAPIClient
            >>>
            >>> client = MyAppAPIClient()
            >>> r = client.Auth.login(username="foo", password="bar")
            >>> # Above API call can be also done directly from the endpoint object, if you need to:
            >>> endpoint = client.Auth.login.endpoint
            >>> r2 = endpoint(client, username="foo", password="bar")
        """
        return self._call(api_client, *args, **kwargs)  # type: ignore[arg-type]

    def _call(
        self,
        api_client: APIClientT,
        *args: Any,
        quiet: bool = False,
        with_hooks: bool = True,
        raw_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> RestResponse:
        """Make an API call directly from this endpoint obj to the associated endpoint (implementation)

        :param api_client: API client to use for the call
        :param args: Endpoint parameters provided as positional arguments (path and/or body/query parameters)
        :param quiet: A flag to suppress API request/response log
        :param with_hooks: Invoke pre/post request hooks
        :param raw_options: Raw request options passed to the underlying HTTP library
        :param kwargs: Endpoint parameters provided as keyword arguments (path and/or body/query parameters)
        """
        api_class = self.api_class(api_client)
        endpoint_func = getattr(api_class, self.func_name)
        return endpoint_func(*args, quiet=quiet, with_hooks=with_hooks, raw_options=raw_options, **kwargs)
