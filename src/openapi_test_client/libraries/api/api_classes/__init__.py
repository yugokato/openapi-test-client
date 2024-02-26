import inspect
import itertools
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from openapi_test_client.libraries.common.misc import import_module_from_file_path

from .base import APIBase

if TYPE_CHECKING:
    APIClassType = TypeVar("APIClassType", bound=APIBase)


def init_api_classes(base_api_class: type["APIClassType"]) -> list[type["APIClassType"]]:
    """Initialize API classes and return a list of API classes.

    - A list of Endpoint objects for an API class is available via its `endpoints` attribute
    - A list of Endpoint objects for all API classes is available via the base API class's `endpoints` attribute

    Note: This function must be called from the __init__.py of a directory that contains API class files

    Example:
        `AuthAPI.endpoints` or `<SampleAppAPIClient>.AUTH.endpoints` will return the following `Endpoint` objects

        >>> from openapi_test_client.clients.sample_app import SampleAppAPIClient
        >>>
        >>> client = SampleAppAPIClient()
        >>> client.AUTH.endpoints
        [
            Endpoint(tag='Auth', api_class=<class 'test_client.clients.sample_app.api.auth.AuthAPI'>, method='post', path='/v1/auth/login', func_name='login', model=<class 'types.LoginEndpointModel'>),
            Endpoint(tag='Auth', api_class=<class 'test_client.clients.sample_app.api.auth.AuthAPI'>, method='get', path='/v1/auth/logout', func_name='logout', model=<class 'types.LogoutEndpointModel'>)
        ]

    """
    from openapi_test_client.libraries.api import Endpoint

    previous_frame = inspect.currentframe().f_back
    caller_file_path = inspect.getframeinfo(previous_frame).filename
    assert caller_file_path.endswith(
        "__init__.py"
    ), f"API classes must be initialized in __init__.py. Unexpectedly called from {caller_file_path}"

    # Set each API class's available Endpoint objects to its endpoints attribute
    api_classes = get_api_classes(Path(caller_file_path).parent, base_api_class)
    for api_class in api_classes:
        if isinstance(api_class.TAGs, property):
            raise RuntimeError(f"API class {api_class.__name__} does not have TAGs been set")
        if not isinstance(api_class.endpoints, list):
            setattr(api_class, "endpoints", [])
        for attr_str in api_class.__dict__:
            if attr_str.startswith("__"):
                continue
            attr = getattr(api_class, attr_str)
            if hasattr(attr, "endpoint") and isinstance(attr.endpoint, Endpoint):
                api_class.endpoints.append(attr.endpoint)

    # Set all API class' Endpoint objects to the base class's endpoint attribute
    base_api_class.endpoints = sorted(
        list(itertools.chain(*[x.endpoints for x in api_classes if x.endpoints])),
        key=lambda x: (", ".join(x.tags), x.method, x.path),
    )
    return sorted(api_classes, key=lambda x: x.TAGs)


def get_api_classes(api_class_dir: Path, base_api_class: type["APIClassType"]) -> list[type["APIClassType"]]:
    """Get all API classes defined under the given API class directory"""
    assert api_class_dir.is_dir()

    api_modules = [import_module_from_file_path(f) for f in api_class_dir.glob("*.py") if not f.stem.startswith("__")]
    if not api_modules:
        raise RuntimeError(f"Found no API class modules in {api_class_dir}")

    api_classes = [
        getattr(mod, x)
        for mod in api_modules
        for x in dir(mod)
        if inspect.isclass(getattr(mod, x))
        and issubclass(getattr(mod, x), base_api_class)
        and x != base_api_class.__name__
    ]
    assert (
        api_classes
    ), f"Unable to find any API class that is a subclass of {base_api_class.__name__} in {api_class_dir}"
    return api_classes
