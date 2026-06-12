"""Unit tests for endpoints_func.py

NOTE: Any tests related to endpoint function calls (__call__, stream(), with_xxx()) should be tested in
test_endpoint_func_call.py
"""

import re
from dataclasses import MISSING
from typing import Annotated, Any
from unittest.mock import MagicMock

import pytest
from common_libs.clients.rest_client import RestResponse
from httpx import Client
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.utils.endpoint_call as endpoint_call_util
from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.core.endpoints import (
    AsyncEndpointFunc,
    Endpoint,
    EndpointFunc,
    SyncEndpointFunc,
    endpoint,
)
from openapi_test_client.libraries.core.types import Alias, EndpointModel, Query, Unset

pytestmark = [pytest.mark.unittest]


class TestEndpointFunc:
    """Tests for core EndpointFunc behavior"""

    @pytest.mark.parametrize("api_client", ["sync", "async"], indirect=True)
    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_func_access(self, api_client: APIClient, api_class: type[APIBase], access_by: str) -> None:
        """Test that accessing endpoint via API class or instance returns an EndpointFunc, and the correct subclass
        based on async_mode
        """
        if access_by == "instance":
            api_class_or_instance = api_class(api_client)
        else:
            api_class_or_instance = api_class
        endpoint_func = api_class_or_instance.get_something
        assert isinstance(endpoint_func, EndpointFunc)

        if access_by == "instance" and api_client.async_mode:
            assert isinstance(endpoint_func, AsyncEndpointFunc)
        else:
            assert isinstance(endpoint_func, SyncEndpointFunc)

    def test_repr(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.__repr__ contains 'mapped to' reference to original function"""
        instance = api_class(api_client)
        repr_str = repr(instance.get_something)
        assert "mapped to" in repr_str

    @pytest.mark.parametrize("access_by", ["instance", "class"])
    def test_endpoint_property_returns_endpoint_object(
        self, api_client: APIClient, api_class: type[APIBase], access_by: str
    ) -> None:
        """Test that EndpointFunc.endpoint returns an Endpoint object"""
        if access_by == "instance":
            api_class_or_instance = api_class(api_client)
        else:
            api_class_or_instance = api_class
        endpoint = api_class_or_instance.get_something.endpoint
        assert isinstance(endpoint, Endpoint)

    def test_model_property_returns_endpoint_model(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.model returns a subclass of EndpointModel"""

        instance = api_class(api_client)
        endpoint_func = instance.get_something
        endpoint_model = endpoint_func.model
        assert issubclass(endpoint_model, EndpointModel)

    def test_model_property_name(self, api_client: APIClient, api_class: type[APIBase]) -> None:
        """Test that EndpointFunc.model name follows <APIClass><FuncName>EndpointModel convention"""

        instance = api_class(api_client)
        endpoint_func = instance.get_something
        assert endpoint_func.model.__name__ == "TestAPIGetSomethingEndpointModel"

    def test_endpoint_func_call_requires_instance(self, api_class: type[APIBase]) -> None:
        """Test that calling __call__() raises TypeError when accessed without an API instance"""
        endpoint_func = api_class.get_something
        assert endpoint_func._instance is None
        with pytest.raises(
            TypeError,
            match=re.escape(
                f"You cannot access {endpoint_func.__name__}() directly through the {api_class.__name__} class."
            ),
        ):
            endpoint_func()

    def test_requires_instance_method_name_for_non_call_method(self, api_class: type[APIBase]) -> None:
        """Test that requires_instance uses the method name (not original func name) for non-__call__ methods

        requires_instance has branching logic: it uses self._original_func.__name__ when f.__name__ == "__call__"
        but f.__name__ otherwise. This test covers the non-__call__ branch (e.g. with_retry).
        """
        endpoint_func = api_class.get_something
        assert endpoint_func._instance is None
        with pytest.raises(
            TypeError,
            match=re.escape(f"You cannot access with_retry() directly through the {api_class.__name__} class."),
        ):
            endpoint_func.with_retry()


class TestEndpointParamDefinition:
    """Tests for the flexible parameter definition feature.

    Path parameters are identified by matching their names against {placeholder} tokens in the endpoint path.
    Both path and Non-path parameters can be passed either positionally or as keyword arguments.
    """

    def _make_api(self, api_client: APIClient) -> type[APIBase]:
        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer(self, customer_id: int, customer_type: str) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}/orders/{order_id}")
            def get_order(self, customer_id: int, order_id: int, status: str) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer_with_defaults(
                self, customer_id: int = 99, customer_type: str | None = None
            ) -> RestResponse: ...

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer_positional_only(self, customer_id: int, /, customer_type: str) -> RestResponse: ...

        return TestAPI

    def _spy_path_and_params(self, mocker: MockerFixture) -> Any:
        mocker.patch.object(Client, "request")
        return mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["validate_path_and_params"]),
            "validate_path_and_params",
        )

    @staticmethod
    def _body_params(spy: Any) -> dict[str, Any]:
        """Extract body/query params from validate_path_and_params spy call args."""
        return {k: v for k, v in spy.call_args.kwargs.items() if k != "raw_options"}

    def test_path_positional_body_positional(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that both path and body params can be passed positionally."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(1, "premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_path_positional_body_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that path param is positional while body param is a keyword argument."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(1, customer_type="premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_path_keyword_body_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that path and body params are both passed as keyword arguments."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer(customer_id=1, customer_type="premium")

        assert spy.spy_return == "/v1/customers/1"
        assert self._body_params(spy) == {"customer_type": "premium"}

    def test_multiple_path_params_positional(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that multiple path params can be passed positionally with body mixed in."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_order(10, 42, "active")

        assert spy.spy_return == "/v1/customers/10/orders/42"
        assert self._body_params(spy) == {"status": "active"}

    def test_multiple_path_params_keyword(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that multiple path params can be passed as keyword arguments."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_order(order_id=42, customer_id=10, status="active")

        assert spy.spy_return == "/v1/customers/10/orders/42"
        assert self._body_params(spy) == {"status": "active"}

    def test_path_param_default_applied_when_omitted(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a path parameter's signature default is used when the caller omits it."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_with_defaults()  # customer_id defaults to 99

        assert spy.spy_return == "/v1/customers/99"
        assert self._body_params(spy) == {}

    def test_path_param_default_overridden(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an explicitly supplied value overrides the path param's default."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_with_defaults(customer_id=5)

        assert spy.spy_return == "/v1/customers/5"
        assert self._body_params(spy) == {}

    def test_body_param_default_not_auto_applied_to_hook(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that body/query param defaults are NOT auto-included in pre_request_hook kwargs."""
        captured: list[dict[str, Any]] = []

        class TestAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, endpoint: Any, *args: Any, **params: Any) -> None:
                captured.append(dict(params))

            @endpoint.get("/v1/customers/{customer_id}")
            def get_customer(self, customer_id: int = 99, customer_type: str | None = None) -> RestResponse: ...

        mocker.patch.object(Client, "request")
        instance = TestAPI(api_client)
        instance.get_customer()  # neither supplied

        # Hook should see only user-provided body/query params (none in this call)
        assert captured == [{}]

    def test_positional_only_path_param(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that existing positional-only path param works."""
        spy = self._spy_path_and_params(mocker)
        instance = self._make_api(api_client)(api_client)
        instance.get_customer_positional_only(7, "vip")

        assert spy.spy_return == "/v1/customers/7"
        assert self._body_params(spy) == {"customer_type": "vip"}

    def test_missing_required_path_param_raises(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that omitting a required path param (no default) raises a descriptive ValueError."""
        mocker.patch.object(Client, "request")
        instance = self._make_api(api_client)(api_client)

        with pytest.raises(ValueError, match="missing 1 required path parameter"):
            instance.get_customer(customer_type="premium")  # customer_id omitted

    def test_non_identifier_placeholder_matched_by_cleaned_name_positional(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that {customer-id} placeholder is matched against the cleaned param name 'customer_id'."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer(42)

        assert spy.spy_return == "/v1/customers/42"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_matched_by_cleaned_name_keyword(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that {customer-id} placeholder is matched when the param is passed as a keyword argument."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer(customer_id=42)

        assert spy.spy_return == "/v1/customers/42"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_default_applied(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a signature default is applied for a non-identifier placeholder param."""
        spy = self._spy_path_and_params(mocker)

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int = 7) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.get_customer()  # uses default

        assert spy.spy_return == "/v1/customers/7"
        assert self._body_params(spy) == {}

    def test_non_identifier_placeholder_model_categorization(self, api_client: APIClient) -> None:
        """Test that create_endpoint_model recognises a cleaned-name param as a path field."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int, role: str) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_customer.model
        fields = model.__dataclass_fields__

        # customer_id matched {customer-id} → path field, no default
        assert "customer_id" in fields
        assert fields["customer_id"].default is MISSING
        # role is body/query → has default (Unset)
        assert fields["role"].default is not MISSING

    def test_non_identifier_placeholder_body_default_not_leaked(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that a body/query default is not leaked into the hook when using a non-identifier placeholder."""
        captured: list[dict[str, Any]] = []

        class TestAPI(APIBase):
            app_name = api_client.app_name

            def pre_request_hook(self, endpoint: Any, *args: Any, **params: Any) -> None:
                captured.append(dict(params))

            @endpoint.get("/v1/customers/{customer-id}")
            def get_customer(self, customer_id: int, role: str | None = None) -> RestResponse: ...

        mocker.patch.object(Client, "request")
        instance = TestAPI(api_client)
        instance.get_customer(5)  # role not supplied

        assert captured == [{}]


class TestEndpointFuncSignatureDefaults:
    """Tests for signature-default merging and Unset-exclusion behavior."""

    @pytest.fixture(autouse=True)
    def _mock_request(self, mocker: MockerFixture) -> None:
        mocker.patch.object(Client, "request")

    @pytest.fixture(autouse=True)
    def spy_generate(self, mocker: MockerFixture) -> MagicMock:
        return mocker.spy(
            __import__(endpoint_call_util.__name__, fromlist=["generate_rest_func_params"]),
            "generate_rest_func_params",
        )

    def test_defaults_merged_to_payload(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that endpoint signature defaults are included in the request payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = "anon", count: int = 0, tag: str | None = None) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item()

        spy_generate.assert_called_once()
        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {"name": "anon", "count": 0, "tag": None}

    def test_unset_is_excluded_from_payload(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that endpoint signature defaults with the Unset sentinel are excluded from the request payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = Unset, count: int = Unset, tag: str = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item()

        spy_generate.assert_called_once()
        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {}

    def test_explicit_params_override_defaults(self, spy_generate: MagicMock, api_client: APIClient) -> None:
        """Test that explicitly-supplied params override signature defaults in the payload."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items")
            def create_item(self, *, name: str = "anon", count: int = 0, tag: str = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.create_item(name="alice", count=5, tag="thing")

        endpoint_params = spy_generate.call_args.args[1]
        assert endpoint_params == {"name": "alice", "count": 5, "tag": "thing"}


class TestEndpointModelFieldDefaults:
    def test_endpoint_model_field_defaults(self, api_client: APIClient) -> None:
        """Test endpoint model field gets correct default value."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/customers/{customer_id}/orders/{order_id}")
            def get_item(
                self, customer_id: int, order_id: int = 1, name: str = "x", tag: str | None = None
            ) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_item.model
        fields = model.__dataclass_fields__

        assert fields["customer_id"].default is MISSING
        assert fields["customer_id"].metadata.get("path") is True
        assert fields["order_id"].default == 1
        assert fields["order_id"].metadata.get("path") is True
        assert fields["name"].default == "x"
        assert fields["name"].metadata == {}
        assert fields["tag"].default is None
        assert fields["tag"].metadata == {}

    def test_endpoint_model_no_default_body_param_gets_unset(self, api_client: APIClient) -> None:
        """Test that a body/query param with no signature default gets Unset in the model."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.get("/v1/items/{item_id}")
            def get_item(self, item_id: int, param1: str) -> RestResponse: ...

        instance = TestAPI(api_client)
        model = instance.get_item.model
        fields = model.__dataclass_fields__

        assert fields["item_id"].default is MISSING
        assert fields["param1"].default is Unset


class TestQueryMarkerRouting:
    """Tests for per-parameter Query marker routing behavior.

    A parameter annotated with Annotated[T, Query()], Annotated[T, Query] (bare class), or the legacy
    Annotated[T, "query"] on a non-GET endpoint must be sent as a URL query string, not in the request body.
    All three forms must produce identical behavior.
    """

    def _make_request_and_capture(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> dict[str, Any]:
        """Helper: call the single endpoint on api_class with mode='test' and return httpx call kwargs."""
        mock_request = mocker.patch.object(Client, "request")
        instance = api_class(api_client)
        instance.update_item(item_id=1, mode="test")
        return mock_request.call_args.kwargs

    @pytest.mark.parametrize("metadata", [Query(), Query, "query"])
    def test_query_marker_routes_to_query_string(
        self, mocker: MockerFixture, api_client: APIClient, metadata: Query | type[Query] | str
    ) -> None:
        """Test that Annotated[T, <query metadata>] sends the param as a URL query string on a non-GET endpoint."""

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, metadata] = Unset) -> RestResponse: ...

        kwargs = self._make_request_and_capture(mocker, api_client, TestAPI)

        assert kwargs.get("params") == {"mode": "test"}
        assert "mode" not in (kwargs.get("json") or {})

    def test_query_marker_routes_none_to_query_string(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an explicit None value for a Query-annotated param is sent as a query string param, not the body.

        None reaches the query string as an empty value (?mode=), preserving the Unset-vs-None
        distinction: Unset omits the param entirely; None sends it with an empty value.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, Query()] = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, mode=None)
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"mode": None}
        assert "mode" not in (kwargs.get("json") or {})

    def test_query_marker_routes_mismatched_type_to_query_string(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that a type-mismatched value for a Query-annotated param still routes to the query string.

        Routing follows the annotation, not the runtime value. This is intentional: the client
        is designed for negative testing and must allow deliberately wrong-typed values.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(self, item_id: int, *, mode: Annotated[str, Query()] = Unset) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, mode=123)  # int given for str-annotated Query param
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"mode": 123}
        assert "mode" not in (kwargs.get("json") or {})

    def test_alias_preserved_for_mismatched_type(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that an Alias is applied even when the runtime value does not match the declared type.

        Alias resolution follows the annotation, not the runtime value.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                content_type: Annotated[str, Alias("Content-Type"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)
        instance.update_item(item_id=1, content_type=123)  # int given for str-annotated param
        kwargs = mock_request.call_args.kwargs

        assert kwargs.get("params") == {"Content-Type": 123}
        assert "content_type" not in (kwargs.get("json") or {})
        assert "Content-Type" not in (kwargs.get("json") or {})

    def test_union_annotated_picks_matching_variant(self, mocker: MockerFixture, api_client: APIClient) -> None:
        """Test that a union of Annotated[] types picks the variant matching the given value's type."""
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                value: Annotated[str, Query()] | Annotated[int, Alias("n"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)

        # int value → Annotated[int, Alias("n"), Query()] selected → alias "n" applied
        instance.update_item(item_id=1, value=42)
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"n": 42}
        assert "value" not in (kwargs.get("json") or {})

        # str value → Annotated[str, Query()] selected → param name "value" kept
        instance.update_item(item_id=1, value="hello")
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"value": "hello"}

    def test_union_annotated_falls_back_to_first_variant_on_no_match(
        self, mocker: MockerFixture, api_client: APIClient
    ) -> None:
        """Test that when no union variant matches, the first variant is used as a fallback.

        Routing must still happen (the param must reach the query string) even when the given value
        does not match any of the declared union variants.
        """
        mock_request = mocker.patch.object(Client, "request")

        class TestAPI(APIBase):
            app_name = api_client.app_name

            @endpoint.post("/v1/items/{item_id}")
            def update_item(
                self,
                item_id: int,
                *,
                # First variant: Annotated[str, Query()] — will be selected as fallback
                # Second variant: Annotated[int, Alias("n"), Query()]
                value: Annotated[str, Query()] | Annotated[int, Alias("n"), Query()] = Unset,
            ) -> RestResponse: ...

        instance = TestAPI(api_client)

        # list value matches neither str nor int → falls back to first variant → no alias, routed to query
        instance.update_item(item_id=1, value=[1, 2, 3])
        kwargs = mock_request.call_args.kwargs
        assert kwargs.get("params") == {"value": [1, 2, 3]}
        assert "value" not in (kwargs.get("json") or {})
