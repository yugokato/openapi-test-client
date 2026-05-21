"""Unit tests for endpoint_factory.py"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial, wraps
from typing import Any, ParamSpec, TypeVar

import pytest
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.libraries.common.constants import VALID_METHODS
from openapi_test_client.libraries.core.api_classes.base import APIBase
from openapi_test_client.libraries.core.endpoints import EndpointHandler, endpoint
from openapi_test_client.libraries.core.endpoints.endpoint_handler import PendingHandler

P = ParamSpec("P")
R = TypeVar("R")

pytestmark = [pytest.mark.unittest]


class TestEndpointFactory:
    """Tests for endpoint factory with endpoint.<method>(<path>) decorators"""

    @pytest.mark.parametrize("method", VALID_METHODS)
    def test_endpoint_factory_creates_endpoint_handler(self, method: str) -> None:
        """Test that each HTTP method decorator returns a decorator that creates an EndpointHandler"""
        path = "/v1/something"
        endpoint_factory = getattr(endpoint, method)(path)

        def do_something(self: Any) -> RestResponse: ...

        endpoint_handler = endpoint_factory(do_something)
        assert isinstance(endpoint_handler, EndpointHandler)
        assert endpoint_handler.method == method
        assert endpoint_handler.path == path
        assert endpoint_handler.use_query_string is (method == "get")
        assert endpoint_handler.original_func is do_something

    def test_endpoint_factory_with_use_query_string_opt(self) -> None:
        """Test that use_query_string can be overridden for non-GET methods"""

        @endpoint.post("/v1/something", use_query_string=True)
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.use_query_string is True

    def test_endpoint_factory_with_default_raw_options(self) -> None:
        """Test that raw options are stored in handler's default_raw_options"""

        @endpoint.get("/v1/something", timeout=30, follow_redirects=True)
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.default_raw_options == {"timeout": 30, "follow_redirects": True}

    def test_endpoint_factory_default_raw_options(self) -> None:
        """Test that default_raw_options is empty dict when no raw options are given"""

        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.default_raw_options == {}


class TestEndpointMetadataDecorators:
    """Tests for endpoint metadata decorators: undocumented, is_public, is_deprecated, content_type"""

    def test_endpoint_is_undocumented(self) -> None:
        """Test that endpoint.undocumented sets is_documented=False on EndpointHandler"""

        @endpoint.undocumented
        @endpoint.get("/v1/hidden")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_documented is False

    def test_endpoint_is_documented_default_is_true(self) -> None:
        """Test that EndpointHandler sets is_documented=True by default"""

        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_documented is True

    def test_endpoint_is_undocumented_on_class_level(self) -> None:
        """Test that endpoint.undocumented can be set on the API class level"""

        @endpoint.undocumented
        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = "test"

        assert TestAPI.is_documented is False

    def test_endpoint_is_public(self) -> None:
        """Test that endpoint.is_public sets is_public=True on EndpointHandler"""

        @endpoint.is_public
        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_public is True

    def test_endpoint_is_public_default_is_false(self) -> None:
        """Test that EndpointHandler is_public=False by default"""

        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_public is False

    def test_endpoint_is_deprecated(self) -> None:
        """Test that endpoint.is_deprecated sets is_deprecated=True on EndpointHandler"""

        @endpoint.is_deprecated
        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_deprecated is True

    def test_endpoint_is_deprecated_default_is_false(self) -> None:
        """Test that EndpointHandler is_deprecated=False by default"""

        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.is_deprecated is False

    def test_endpoint_is_deprecated_on_class_level(self) -> None:
        """Test that endpoint.is_deprecated can be set on the class level"""

        @endpoint.is_deprecated
        class TestAPI(APIBase):
            TAGs = ("Test",)
            app_name = "test"

        assert TestAPI.is_deprecated is True

    def test_endpoint_content_type(self) -> None:
        """Test that endpoint.content_type() sets content_type on EndpointHandler"""

        @endpoint.content_type("application/xml")
        @endpoint.post("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.content_type == "application/xml"

    def test_endpoint_content_type_default_is_none(self) -> None:
        """Test that EndpointHandler content_type=None by default"""

        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert do_something.content_type is None


class TestEndpointDecoratorRegistration:
    """Tests endpoint decorator registration with endpoint.decorator()"""

    @pytest.mark.parametrize("with_args", [False, True])
    def test_endpoint_decorator_registration(self, with_args: bool) -> None:
        """Test that endpoint.decorator registers a decorator on EndpointHandler"""

        if with_args:

            @endpoint.decorator
            def decorator_with_args(*deco_args: Any, **deco_kwargs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
                def decorator(f: Callable[P, R]) -> Callable[P, R]:
                    @wraps(f)
                    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                        return f(*args, **kwargs)

                    return wrapper

                return decorator

            decorator = decorator_with_args("a", "b", c=123)
        else:

            @endpoint.decorator
            def regular_decorator(f: Callable[P, R]) -> Callable[P, R]:
                @wraps(f)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return f(*args, **kwargs)

                return wrapper

            decorator = regular_decorator

        @decorator
        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert len(do_something.decorators) == 1
        registered_decorator = do_something.decorators[0]
        if with_args:
            assert isinstance(registered_decorator, partial)
            assert registered_decorator.func is decorator.__wrapped__
        else:
            assert registered_decorator is decorator.__wrapped__

    def test_endpoint_decorator_registration_multi(self) -> None:
        """Test that multiple endpoint.decorator registers all decorators"""

        @endpoint.decorator
        def deco1(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        @endpoint.decorator
        def deco2(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        @deco1
        @deco2
        @endpoint.get("/v1/something")
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert len(do_something.decorators) == 2
        assert do_something.decorators == [deco2.__wrapped__, deco1.__wrapped__]


class TestDecoratorPositionIndependence:
    """Tests for endpoint_factory.py position-independent decorator behavior"""

    def test_method_decorator_above_is_public(self) -> None:
        """Test that endpoint.is_public works when placed below @endpoint.<method>()"""

        @endpoint.post("/v1/something")
        @endpoint.is_public
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.is_public is True

    def test_method_decorator_above_is_deprecated(self) -> None:
        """Test that endpoint.is_deprecated works when placed below @endpoint.<method>()"""

        @endpoint.post("/v1/something")
        @endpoint.is_deprecated
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.is_deprecated is True

    def test_method_decorator_above_undocumented(self) -> None:
        """Test that endpoint.undocumented works when placed below @endpoint.<method>()"""

        @endpoint.get("/v1/something")
        @endpoint.undocumented
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.is_documented is False

    def test_method_decorator_above_content_type(self) -> None:
        """Test that endpoint.content_type() works when placed below @endpoint.<method>()"""

        @endpoint.post("/v1/something")
        @endpoint.content_type("application/xml")
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.content_type == "application/xml"

    def test_method_decorator_outermost_all_flags_below(self) -> None:
        """Test that @endpoint.<method>() works as the outermost decorator with all flags below it"""

        @endpoint.post("/v1/something")
        @endpoint.is_public
        @endpoint.is_deprecated
        @endpoint.content_type("application/xml")
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.is_public is True
        assert do_something.is_deprecated is True
        assert do_something.content_type == "application/xml"

    def test_method_decorator_in_middle(self) -> None:
        """Test that @endpoint.<method>() works in the middle with flags both above and below"""

        @endpoint.is_public
        @endpoint.post("/v1/something")
        @endpoint.is_deprecated
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.is_public is True
        assert do_something.is_deprecated is True

    def test_original_func_preserved_when_factory_outermost(self) -> None:
        """Test that original_func on the EndpointHandler points to the real function when flags are below"""

        @endpoint.post("/v1/something")
        @endpoint.is_public
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert do_something.original_func.__name__ == "do_something"

    def test_endpoint_decorator_below_method_decorator(self) -> None:
        """Test that an @endpoint.decorator-wrapped decorator works when placed below @endpoint.<method>()"""

        @endpoint.decorator
        def my_decorator(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        @endpoint.get("/v1/something")
        @my_decorator
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert len(do_something.decorators) == 1
        assert do_something.decorators[0] is my_decorator.__wrapped__

    def test_endpoint_decorator_order_preserved_when_mixed(self) -> None:
        """Test that decorator registration order is the same regardless of position relative to @endpoint.<method>()"""

        @endpoint.decorator
        def deco1(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        @endpoint.decorator
        def deco2(f: Callable[P, R]) -> Callable[P, R]:
            @wraps(f)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                return f(*args, **kwargs)

            return wrapper

        # All above (baseline)
        @deco1
        @deco2
        @endpoint.get("/v1/something")
        def all_above(self: Any) -> RestResponse: ...

        # All below (method decorator outermost)
        @endpoint.get("/v1/something")
        @deco1
        @deco2
        def all_below(self: Any) -> RestResponse: ...

        # Mixed (method decorator in the middle)
        @deco1
        @endpoint.get("/v1/something")
        @deco2
        def mixed(self: Any) -> RestResponse: ...

        expected_order = [deco2.__wrapped__, deco1.__wrapped__]
        assert all_above.decorators == expected_order
        assert all_below.decorators == expected_order
        assert mixed.decorators == expected_order

    def test_endpoint_decorator_with_args_below_method_decorator(self) -> None:
        """Test that @endpoint.decorator-wrapped decorators with args work when placed below the method decorator"""

        @endpoint.decorator
        def decorator_with_args(*deco_args: Any, **deco_kwargs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
            def decorator(f: Callable[P, R]) -> Callable[P, R]:
                @wraps(f)
                def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    return f(*args, **kwargs)

                return wrapper

            return decorator

        @endpoint.get("/v1/something")
        @decorator_with_args("x", key="val")
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, EndpointHandler)
        assert len(do_something.decorators) == 1
        registered = do_something.decorators[0]
        assert isinstance(registered, partial)
        assert registered.func is decorator_with_args.__wrapped__

    def test_missing_method_decorator_produces_pending_endpoint(self) -> None:
        """Test that applying a flag decorator without @endpoint.<method>() produces a _PendingEndpoint"""

        @endpoint.is_public
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, PendingHandler)
        assert not isinstance(do_something, EndpointHandler)

    def test_multiple_flags_without_method_decorator_accumulate_in_pending(self) -> None:
        """Test that multiple flag decorators without @endpoint.<method>() accumulate ops in _PendingEndpoint"""

        @endpoint.is_public
        @endpoint.is_deprecated
        def do_something(self: Any) -> RestResponse: ...

        assert isinstance(do_something, PendingHandler)
        assert len(do_something.deferred_operations) == 2
