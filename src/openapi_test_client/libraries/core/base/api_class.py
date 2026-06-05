from __future__ import annotations

import importlib
import inspect
import itertools
import pkgutil
import sys
from abc import ABCMeta
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from common_libs.logging import get_logger
from httpx import HTTPError

from ..endpoints import Endpoint
from ..endpoints.endpoint_func import AsyncEndpointFunc, SyncEndpointFunc
from ..types import RestResponse

if TYPE_CHECKING:
    from .api_client import APIClient


APIClassT = TypeVar("APIClassT", bound="APIBase[Any]")
APIClientT = TypeVar("APIClientT", bound="APIClient")

logger = get_logger(__name__)


class APIBase(Generic[APIClientT], metaclass=ABCMeta):
    """Base API class"""

    app_name: str | None = None
    is_documented: bool = True
    is_deprecated: bool = False
    endpoints: list[Endpoint[Any]] | None = None
    _endpoint_class: ClassVar[type[Endpoint[Any]]] = Endpoint
    _sync_endpoint_func_class: ClassVar[type[SyncEndpointFunc[Any]]] = SyncEndpointFunc
    _async_endpoint_func_class: ClassVar[type[AsyncEndpointFunc[Any]]] = AsyncEndpointFunc

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the endpoint decorator stack when an API class is defined."""
        super().__init_subclass__(**kwargs)
        from ..endpoints.endpoint_handler import EndpointHandler, PendingHandler

        def wraps_handler(func: Any, _depth: int = 10) -> bool:
            if _depth == 0:
                return False
            if isinstance(inspect.unwrap(func), (EndpointHandler, PendingHandler)):
                return True
            if func.__closure__:
                for cell in func.__closure__:
                    try:
                        cell_content = cell.cell_contents
                        if isinstance(cell_content, (EndpointHandler, PendingHandler)):
                            return True
                        if inspect.isfunction(cell_content) and wraps_handler(cell_content, _depth - 1):
                            return True
                    except ValueError:
                        pass
            return False

        for attr_name, attr in cls.__dict__.items():
            func = attr.func if isinstance(attr, PendingHandler) else attr
            if inspect.isfunction(func) and wraps_handler(func):
                raise RuntimeError(
                    f"{cls.__name__}.{attr_name}: Detected an unregistered decorator on this API function. "
                    f"Decorators must be registered by applying @endpoint.decorator on the decorator definition."
                )
            elif isinstance(attr, PendingHandler):
                raise RuntimeError(
                    f"{cls.__name__}.{attr_name}: Invalid API function definition. Requires @endpoint.<method>() "
                    f"decorator."
                )

    def __init__(self, api_client: APIClientT):
        if self.app_name != api_client.app_name:
            raise ValueError(
                f"app_name for API class ({self.app_name}) and API client ({api_client.app_name}) must match"
            )
        self.env = api_client.env
        self.api_client = api_client
        self.rest_client = api_client.rest_client

    def pre_request_hook(self, endpoint: Endpoint[Any], *path_params: Any, **params: Any) -> None:
        """Hook function called before each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param path_params: API path parameters
        :param params: API parameters sent with the request
        """
        ...

    def post_request_hook(
        self,
        endpoint: Endpoint[Any],
        response: RestResponse | None,
        exception: HTTPError | None,
        *path_params: Any,
        **params: Any,
    ) -> None:
        """Hook function called after each request

        :param endpoint: Endpoint object associated with an endpoint function called
        :param response: Response of the API request
        :param exception: An exception raised in the httpx client
        :param path_params: API path parameters for the request
        :param params: API parameters sent with the request
        """
        ...

    def request_wrapper(self) -> list[Callable[..., Any]]:
        """Decorator(s) to wrap each request call

        NOTE:
            - If multiple wrappers are returned, they will be applied from the last one, which means the first one will
              be processed first.
            - The first argument of the wrapper function inside the decorator is an instance of EndpointFunc class
        """
        return []

    def stream_wrapper(self) -> list[Callable[..., Any]]:
        """Decorator(s) to wrap each stream call, analogous to request_wrapper()

        NOTE:
            - If multiple wrappers are returned, they will be applied from the last one, which means the first one will
              be processed first.
            - The first argument of the wrapper function inside the decorator is an instance of EndpointFunc class
        """
        return []

    @classmethod
    def init(cls: type[APIClassT]) -> list[type[APIClassT]]:
        """Initialize API classes and return a list of API classes.

        A list of Endpoint objects for an API class is available via its `endpoints` attribute.
        A list of Endpoint objects for all API classes is available via the base API class's `endpoints` attribute.

        Note: This classmethod must be called from the `__init__.py` of a directory that contains API class files.
        """
        if cls is APIBase:
            raise TypeError(f"init() cannot be called directly from {APIBase.__name__}")

        from ..endpoints.endpoint_func import EndpointFunc
        from ..endpoints.endpoint_handler import EndpointHandler

        previous_frame = inspect.currentframe().f_back
        assert previous_frame
        caller_file_path = inspect.getframeinfo(previous_frame).filename
        if not caller_file_path.endswith("__init__.py"):
            raise RuntimeError(
                f"API classes must be initialized in __init__.py. Unexpectedly initialized from {caller_file_path}"
            )
        api_module: str = previous_frame.f_globals["__name__"]
        api_classes = get_api_classes(api_module, cls)

        for api_class in api_classes:
            api_class.endpoints = []
            for attr_name, attr in api_class.__dict__.items():
                if isinstance(attr, EndpointHandler):
                    endpoint_func: EndpointFunc[Any] = getattr(api_class, attr_name)
                    assert isinstance(endpoint_func, EndpointFunc)
                    api_class.endpoints.append(endpoint_func.endpoint)

        cls.endpoints = sorted(
            itertools.chain(*(x.endpoints for x in api_classes if x.endpoints)),
            key=lambda x: (x.api_class.__name__, x.method, x.path),
        )
        return api_classes


def get_api_classes(api_module_name: str, base_api_class: type[APIClassT]) -> list[type[APIClassT]]:
    """Get all API classes subclassed from the base defined in an API module"""
    mod = sys.modules[api_module_name]
    if not hasattr(mod, "__path__"):
        raise TypeError(f"{api_module_name} is not a package")

    for module_info in pkgutil.walk_packages(mod.__path__, prefix=f"{api_module_name}."):
        if not module_info.name.startswith("__"):
            importlib.import_module(module_info.name)

    api_classes = sorted(
        (
            cls
            for cls in _get_subclasses(base_api_class)
            if cls.__module__.startswith(f"{api_module_name}.")
            and not cls.__name__.startswith("_")
            and _is_live_class(cls)
        ),
        key=lambda cls: cls.__name__,
    )
    if not api_classes:
        raise RuntimeError(f"No subclasses of {base_api_class.__name__} found in '{mod.__path__[0]}'")

    return api_classes


def _get_subclasses(base_api_class: type[APIClassT]) -> set[type[APIClassT]]:
    """Recursively collect all subclasses of the given class."""
    direct: set[type[APIClassT]] = set(base_api_class.__subclasses__())
    return direct.union(*(_get_subclasses(s) for s in direct))


def _is_live_class(cls: type) -> bool:
    """Return whether `cls` is the object currently bound under its own name in its own module.

    Module reloads during code generation create new class objects for the same class name while
    the stale ones remain reachable via `__subclasses__()`. Only the class that is currently
    bound in `sys.modules` under its own name is the live class; stale reload artifacts will
    fail this check and are filtered out.
    """
    module = sys.modules.get(cls.__module__)
    return getattr(module, cls.__name__, None) is cls
