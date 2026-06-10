"""Unit tests for core utils/endpoint_call.py"""

from __future__ import annotations

from dataclasses import field, make_dataclass
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from pytest_mock import MockerFixture

import openapi_test_client.libraries.core.utils.endpoint_call as endpoint_call_util
from openapi_test_client.libraries.core.endpoints.endpoint import Endpoint
from openapi_test_client.libraries.core.types import Alias, EndpointModel, File, Query, Unset

pytestmark = [pytest.mark.unittest]


class _FakeAPIClass:
    """Minimal API class stand-in — only __name__ is required by _check_params."""

    __name__ = "FakeAPI"


def _make_endpoint(
    fields: dict[str, Any] | None = None,
    *,
    path: str = "/v1/test",
    method: str = "POST",
    content_type: str | None = None,
    is_documented: bool = True,
    is_deprecated: bool = False,
    func_name: str = "test_func",
) -> Endpoint:
    """Build a minimal `Endpoint` whose model carries the given field name → annotation mapping.

    :param fields: Mapping of parameter name to its type annotation. Defaults to no fields.
    :param path: Endpoint URL path.
    :param method: HTTP method string.
    :param content_type: Value for `endpoint.content_type`.
    :param is_documented: Whether the endpoint is documented (controls param-warning behaviour).
    :param is_deprecated: Whether the endpoint is deprecated.
    :param func_name: Function name stored on the endpoint.
    """
    field_list = [(name, tp, field(default=Unset)) for name, tp in (fields or {}).items()]
    model = make_dataclass(
        "TestEndpointModel",
        field_list,
        bases=(EndpointModel,),
        namespace={"content_type": content_type, "endpoint_func": None},
        kw_only=True,
        frozen=True,
    )
    return Endpoint(
        api_class=_FakeAPIClass,
        method=method,
        path=path,
        func_name=func_name,
        model=model,
        content_type=content_type,
        is_documented=is_documented,
        is_deprecated=is_deprecated,
    )


class TestGetPathPlaceholders:
    """Tests for endpoint_call_util.get_path_placeholders()"""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/v1/health", ()),
            ("/v1/users/{user_id}", ("user_id",)),
            ("/v1/items/{item-id}", ("item-id",)),
            ("/v1/users/{user_id}/orders/{order_id}", ("user_id", "order_id")),
            ("/v1/{a}/items/{b-c}/sub/{d}", ("a", "b-c", "d")),
        ],
    )
    def test_get_path_placeholders(self, path: str, expected: tuple[str, ...]) -> None:
        """Test that path placeholder names are extracted in order from the endpoint path"""
        assert endpoint_call_util.get_path_placeholders(path) == expected


class TestGetPathParamLookup:
    """Tests for endpoint_call_util.get_path_param_lookup()"""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/v1/health", {}),
            ("/v1/users/{user_id}", {"user_id": "user_id"}),
            # Non-identifier placeholder maps both raw and cleaned forms to the raw placeholder
            ("/v1/items/{item-id}", {"item-id": "item-id", "item_id": "item-id"}),
            # Mixed: identifier and non-identifier in same path
            (
                "/v1/{user_id}/orders/{order-id}",
                {"user_id": "user_id", "order-id": "order-id", "order_id": "order-id"},
            ),
        ],
    )
    def test_get_path_param_lookup(self, path: str, expected: dict[str, str]) -> None:
        """Test that the lookup maps both raw and cleaned caller-facing names to the original placeholder"""
        assert endpoint_call_util.get_path_param_lookup(path) == expected


class TestGetPathParamNames:
    """Tests for endpoint_call_util.get_path_param_names()"""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/v1/health", frozenset()),
            ("/v1/users/{user_id}", frozenset({"user_id"})),
            # Non-identifier placeholder → cleaned form only (callers use Python-valid names)
            ("/v1/items/{item-id}", frozenset({"item_id"})),
        ],
    )
    def test_get_path_param_names(self, path: str, expected: frozenset[str]) -> None:
        """Test that path param names are returned as Python-identifier forms"""
        assert endpoint_call_util.get_path_param_names(path) == expected

    def test_get_path_param_names_multiple_mixed_placeholders(self) -> None:
        """Test that a path with both identifier and non-identifier placeholders returns all cleaned names"""
        # Kept as a dedicated test to avoid frozenset's non-deterministic repr in parametrize IDs
        result = endpoint_call_util.get_path_param_names("/v1/{user_id}/orders/{order-id}")
        assert result == frozenset({"user_id", "order_id"})


class TestGetParamsSignature:
    """Tests for endpoint_call_util.get_params_signature()"""

    def test_self_is_removed_from_signature(self) -> None:
        """Test that the `self` parameter is stripped from the returned signature"""

        def _func(self: Any, user_id: str, name: str = "default") -> None: ...

        sig = endpoint_call_util.get_params_signature(_func)
        assert "self" not in sig.parameters
        assert "user_id" in sig.parameters
        assert "name" in sig.parameters

    def test_function_with_only_self_returns_empty_signature(self) -> None:
        """Test that a function with only `self` produces an empty signature"""

        def _func(self: Any) -> None: ...

        sig = endpoint_call_util.get_params_signature(_func)
        assert len(sig.parameters) == 0


class TestSplitParams:
    """Tests for endpoint_call_util.split_params()"""

    def test_path_and_body_params_are_separated(self) -> None:
        """Test that positional path params and keyword body params are split correctly"""

        def _func(self: Any, user_id: str, name: str) -> None: ...

        path_params, body_params = endpoint_call_util.split_params(
            "/v1/users/{user_id}", _func, ("u123",), {"name": "Alice"}
        )
        assert path_params == {"user_id": "u123"}
        assert body_params == {"name": "Alice"}

    def test_var_keyword_params_are_flattened_into_body(self) -> None:
        """Test that **kwargs captured by a VAR_KEYWORD parameter are flattened into body params"""

        def _func(self: Any, name: str, **kwargs: Any) -> None: ...

        path_params, body_params = endpoint_call_util.split_params(
            "/v1/test", _func, (), {"name": "Alice", "extra": "ext"}
        )
        assert path_params == {}
        assert body_params == {"name": "Alice", "extra": "ext"}

    def test_path_default_is_applied_when_caller_omits_path_param(self) -> None:
        """Test that a path param with a default value is filled when the caller omits it"""

        def _func(self: Any, user_id: str = "default-id") -> None: ...

        path_params, body_params = endpoint_call_util.split_params("/v1/users/{user_id}", _func, (), {})
        assert path_params == {"user_id": "default-id"}
        assert body_params == {}

    def test_non_identifier_placeholder_accepts_cleaned_caller_name(self) -> None:
        """Test that a non-identifier placeholder is matched by the caller's cleaned (Python) name"""

        def _func(self: Any, customer_id: str) -> None: ...

        path_params, body_params = endpoint_call_util.split_params(
            "/v1/customers/{customer-id}", _func, (), {"customer_id": "c123"}
        )
        # The path dict uses the raw placeholder as key
        assert path_params == {"customer-id": "c123"}
        assert body_params == {}

    def test_unknown_kwarg_reraises_as_natural_type_error(self) -> None:
        """Test that an unknown keyword argument causes a natural TypeError including the function name"""

        def _func(self: Any, a: str) -> None: ...

        with pytest.raises(TypeError, match=r"_func\(\) got an unexpected keyword argument 'unknown_kwarg'"):
            endpoint_call_util.split_params("/v1/test", _func, (), {"unknown_kwarg": "val"})

    def test_explicit_unset_path_param_falls_back_to_default(self) -> None:
        """Test that a path param explicitly given as Unset behaves as omitted and uses the signature default"""

        def _func(self: Any, user_id: str = "default-id") -> None: ...

        path_params, body_params = endpoint_call_util.split_params("/v1/users/{user_id}", _func, (), {"user_id": Unset})
        assert path_params == {"user_id": "default-id"}
        assert body_params == {}

    def test_explicit_unset_path_param_without_default_is_dropped(self) -> None:
        """Test that a path param explicitly given as Unset with no default is treated as not provided"""

        def _func(self: Any, user_id: str) -> None: ...

        path_params, body_params = endpoint_call_util.split_params("/v1/users/{user_id}", _func, (), {"user_id": Unset})
        assert path_params == {}
        assert body_params == {}


class TestGetSignatureDefaults:
    """Tests for endpoint_call_util.get_signature_defaults()"""

    def test_path_param_is_excluded(self) -> None:
        """Test that path parameters are excluded from the defaults mapping"""

        def _func(self: Any, user_id: str, name: str = "default") -> None: ...

        result = endpoint_call_util.get_signature_defaults(_func, "/v1/users/{user_id}")
        assert "user_id" not in result
        assert result == {"name": "default"}

    def test_param_with_unset_default_is_excluded(self) -> None:
        """Test that parameters whose default is `Unset` are excluded"""

        def _func(self: Any, a: str = Unset, b: str = "kept") -> None: ...

        result = endpoint_call_util.get_signature_defaults(_func, "/v1/test-unset-exclusion")
        assert "a" not in result
        assert result == {"b": "kept"}

    def test_var_keyword_param_is_excluded(self) -> None:
        """Test that VAR_KEYWORD parameters (**kwargs) are excluded"""

        def _func(self: Any, **kwargs: Any) -> None: ...

        result = endpoint_call_util.get_signature_defaults(_func, "/v1/test-varkw")
        assert result == {}

    def test_param_without_default_is_excluded(self) -> None:
        """Test that parameters with no default value are excluded"""

        def _func(self: Any, a: str) -> None: ...

        result = endpoint_call_util.get_signature_defaults(_func, "/v1/test-no-default")
        assert result == {}

    def test_only_non_path_defaults_with_real_values_are_returned(self) -> None:
        """Test that only body/query params with non-Unset defaults appear in the result"""

        def _func(self: Any, user_id: int = 123, name: str = "Alice", age: int = 30, token: str = Unset) -> None: ...

        result = endpoint_call_util.get_signature_defaults(_func, "/v1/users/{user_id}")
        assert result == {"name": "Alice", "age": 30}
        assert "user_id" not in result
        assert "token" not in result


class TestIsJsonRequest:
    """Tests for endpoint_call_util.is_json_request()"""

    def test_file_field_in_model_is_not_json(self) -> None:
        """Test that an endpoint whose model declares a File field is treated as multipart"""
        endpoint = _make_endpoint({"document": File})
        assert endpoint_call_util.is_json_request(endpoint, {}, {}, {}) is False

    def test_file_value_in_params_is_not_json(self) -> None:
        """Test that passing a File instance as a param value makes the request non-JSON"""
        endpoint = _make_endpoint({"name": str})
        params = {"upload": File("a.txt", b"", "text/plain")}
        assert endpoint_call_util.is_json_request(endpoint, params, {}, {}) is False

    def test_no_content_type_at_all_defaults_to_json(self) -> None:
        """Test that the default when no content type is specified anywhere is JSON"""
        endpoint = _make_endpoint({})
        assert endpoint_call_util.is_json_request(endpoint, {}, {}, {}) is True

    def test_explicit_request_header_application_json_is_json(self) -> None:
        """Test that an explicit `Content-Type: application/json` request header means JSON"""
        endpoint = _make_endpoint({})
        raw_options = {"headers": {"Content-Type": "application/json"}}
        assert endpoint_call_util.is_json_request(endpoint, {}, raw_options, {}) is True

    def test_explicit_request_header_non_json_is_not_json(self) -> None:
        """Test that a non-JSON `Content-Type` request header means non-JSON"""
        endpoint = _make_endpoint({})
        raw_options = {"headers": {"Content-Type": "text/xml"}}
        assert endpoint_call_util.is_json_request(endpoint, {}, raw_options, {}) is False

    def test_explicit_session_header_non_json_is_not_json(self) -> None:
        """Test that a non-JSON `Content-Type` session header means non-JSON"""
        endpoint = _make_endpoint({})
        session_headers = {"Content-Type": "multipart/form-data"}
        assert endpoint_call_util.is_json_request(endpoint, {}, {}, session_headers) is False

    def test_endpoint_content_type_application_json_is_json(self) -> None:
        """Test that `endpoint.content_type = application/json` means JSON"""
        endpoint = _make_endpoint({}, content_type="application/json")
        assert endpoint_call_util.is_json_request(endpoint, {}, {}, {}) is True

    def test_endpoint_content_type_non_json_is_not_json(self) -> None:
        """Test that `endpoint.content_type` set to a non-JSON media type means non-JSON"""
        endpoint = _make_endpoint({}, content_type="text/plain")
        assert endpoint_call_util.is_json_request(endpoint, {}, {}, {}) is False

    def test_content_type_with_charset_suffix_is_parsed_correctly(self) -> None:
        """Test that a `Content-Type` with a charset suffix is parsed as JSON when appropriate"""
        endpoint = _make_endpoint({})
        raw_options = {"headers": {"Content-Type": "application/json; charset=utf-8"}}
        assert endpoint_call_util.is_json_request(endpoint, {}, raw_options, {}) is True


class TestValidatePathAndParams:
    """Tests for endpoint_call_util.validate_path_and_params()"""

    def test_returns_completed_path(self) -> None:
        """Test that the completed URL path (with placeholders filled) is returned"""
        endpoint = _make_endpoint({}, path="/v1/users/{user_id}")
        ef = SimpleNamespace(endpoint=endpoint)
        result = endpoint_call_util.validate_path_and_params(ef, "u123", raw_options=None)
        assert result == "/v1/users/u123"

    def test_path_without_placeholders_returned_unchanged(self) -> None:
        """Test that a path with no placeholders is returned as-is"""
        endpoint = _make_endpoint({}, path="/v1/health")
        ef = SimpleNamespace(endpoint=endpoint)
        result = endpoint_call_util.validate_path_and_params(ef, raw_options=None)
        assert result == "/v1/health"

    def test_deprecated_endpoint_logs_warning(self, mocker: MockerFixture) -> None:
        """Test that calling a deprecated endpoint logs a DEPRECATED warning"""
        endpoint = _make_endpoint({}, path="/v1/old", is_deprecated=True)
        ef = SimpleNamespace(endpoint=endpoint)
        mock_log = mocker.patch.object(endpoint_call_util, "logger")
        endpoint_call_util.validate_path_and_params(ef, raw_options=None)
        mock_log.warning.assert_called_once()
        assert "DEPRECATED" in mock_log.warning.call_args[0][0]

    def test_missing_path_param_raises_value_error(self) -> None:
        """Test that omitting a required path parameter raises ValueError"""
        endpoint = _make_endpoint({}, path="/v1/users/{user_id}")
        ef = SimpleNamespace(endpoint=endpoint)
        with pytest.raises(ValueError, match="missing 1 required path parameter"):
            endpoint_call_util.validate_path_and_params(ef, raw_options=None)

    def test_extra_path_params_raise_value_error(self) -> None:
        """Test that passing more path params than placeholders raises ValueError"""
        endpoint = _make_endpoint({}, path="/v1/users/{user_id}")
        ef = SimpleNamespace(endpoint=endpoint)
        with pytest.raises(ValueError, match="received unexpected 1 extra path parameter"):
            endpoint_call_util.validate_path_and_params(ef, "u123", "extra", raw_options=None)

    def test_invalid_raw_option_raises_runtime_error(self, mocker: MockerFixture) -> None:
        """Test that an unrecognized raw option key raises RuntimeError"""
        mocker.patch(
            "openapi_test_client.libraries.core.utils.endpoint_call.get_supported_request_parameters",
            return_value=set(),
        )
        endpoint = _make_endpoint({})
        ef = SimpleNamespace(endpoint=endpoint)
        with pytest.raises(RuntimeError, match="Invalid raw option"):
            endpoint_call_util.validate_path_and_params(ef, raw_options={"bad_opt": True})

    def test_unexpected_body_param_logs_warning(self, mocker: MockerFixture) -> None:
        """Test that a body param not declared in the model logs a warning"""
        endpoint = _make_endpoint({"expected": str}, is_documented=True)
        ef = SimpleNamespace(endpoint=endpoint)
        mock_log = mocker.patch.object(endpoint_call_util, "logger")
        endpoint_call_util.validate_path_and_params(ef, raw_options=None, unexpected_param="val")
        # At least one warning is expected (unexpected param)
        assert mock_log.warning.called
        warning_messages = [call[0][0] for call in mock_log.warning.call_args_list]
        assert any("unexpected_param" in msg for msg in warning_messages)

    def test_deprecated_param_logs_warning(self, mocker: MockerFixture) -> None:
        """Test that using a deprecated param logs a DEPRECATED warning"""
        endpoint = _make_endpoint({"old_param": Annotated[str, "deprecated"]}, is_documented=True)
        ef = SimpleNamespace(endpoint=endpoint)
        mock_log = mocker.patch.object(endpoint_call_util, "logger")
        endpoint_call_util.validate_path_and_params(ef, raw_options=None, old_param="val")
        assert mock_log.warning.called
        warning_messages = [call[0][0] for call in mock_log.warning.call_args_list]
        assert any("DEPRECATED" in msg for msg in warning_messages)

    def test_unmodeled_params_on_multipart_endpoint_log_warning(self, mocker: MockerFixture) -> None:
        """Test that unknown params passed to a documented multipart endpoint log a warning"""
        endpoint = _make_endpoint({"file": File}, is_documented=True)
        ef = SimpleNamespace(endpoint=endpoint)
        mock_log = mocker.patch.object(endpoint_call_util, "logger")
        endpoint_call_util.validate_path_and_params(
            ef, raw_options=None, file=File("test.txt", b"hello", "text/plain"), unknown_a="val_a", unknown_b=123
        )
        assert mock_log.warning.called
        warning_messages = [call[0][0] for call in mock_log.warning.call_args_list]
        assert any("unknown_a" in msg and "unknown_b" in msg for msg in warning_messages)


class TestGenerateRestFuncParams:
    """Tests for endpoint_call_util.generate_rest_func_params()

    Covers the full routing logic: json/data/params/files bucketing, Alias name
    remapping, Query annotation forwarding, use_query_string override, multipart
    handling, Content-Type header injection, and the unmodeled-param regression guard.
    """

    def test_empty_params_returns_quiet_only(self) -> None:
        """Test that calling with no endpoint params produces only the `quiet` key"""
        endpoint = _make_endpoint({})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {})
        assert result == {"quiet": False}

    def test_quiet_flag_is_propagated(self) -> None:
        """Test that the `quiet` flag is forwarded to the output dict"""
        endpoint = _make_endpoint({})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {}, quiet=True)
        assert result["quiet"] is True

    def test_raw_options_are_included_in_output(self) -> None:
        """Test that extra **raw_options kwargs appear at the top level of the result"""
        endpoint = _make_endpoint({})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {}, timeout=30)
        assert result["timeout"] == 30

    def test_json_param_goes_to_json_key(self) -> None:
        """Test that a regular body param on a JSON endpoint goes to the `json` output key"""
        endpoint = _make_endpoint({"name": str})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"name": "Alice"}, {})
        assert result.get("json") == {"name": "Alice"}
        assert "data" not in result
        assert "params" not in result

    def test_unset_value_is_excluded_from_request(self) -> None:
        """Test that params explicitly given as Unset are excluded from the request entirely"""
        endpoint = _make_endpoint({"name": str, "page": Annotated[int, Query()]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"name": Unset, "page": Unset}, {})
        assert "json" not in result
        assert "params" not in result

    def test_unset_value_suppresses_merged_signature_default(self) -> None:
        """Test that an explicit Unset removes a param even when a concrete signature default was merged in"""
        endpoint = _make_endpoint({"name": str, "page": int})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"name": "Alice", "page": Unset}, {})
        assert result.get("json") == {"name": "Alice"}

    def test_query_annotation_instance_goes_to_params(self) -> None:
        """Test that `Annotated[T, Query()]` routes the param to the `params` (query string) key"""
        endpoint = _make_endpoint({"page": Annotated[int, Query()]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"page": 1}, {})
        assert result.get("params") == {"page": 1}
        assert "json" not in result

    def test_query_annotation_bare_class_goes_to_params(self) -> None:
        """Test that `Annotated[T, Query]` (bare class) routes the param to `params`"""
        endpoint = _make_endpoint({"page": Annotated[int, Query]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"page": 1}, {})
        assert result.get("params") == {"page": 1}

    def test_query_annotation_legacy_string_goes_to_params(self) -> None:
        """Test that `Annotated[T, "query"]` (legacy string) routes the param to `params`"""
        endpoint = _make_endpoint({"page": Annotated[int, "query"]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"page": 1}, {})
        assert result.get("params") == {"page": 1}

    def test_alias_annotation_remaps_output_key(self) -> None:
        """Test that `Annotated[T, Alias("real-name")]` uses the alias as the output key"""
        endpoint = _make_endpoint({"page_num": Annotated[int, Alias("page")]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"page_num": 1}, {})
        json_out = result.get("json", {})
        assert "page" in json_out
        assert "page_num" not in json_out

    def test_alias_and_query_combined_remaps_key_into_params(self) -> None:
        """Test that Alias + Query together remap the key AND route to params"""
        endpoint = _make_endpoint({"page_num": Annotated[int, Alias("page"), Query()]})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"page_num": 2}, {})
        assert result.get("params") == {"page": 2}
        assert "json" not in result

    def test_use_query_string_forces_body_params_to_params(self) -> None:
        """Test that `use_query_string=True` forces all params to the query string"""
        endpoint = _make_endpoint({"name": str})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"name": "Alice"}, {}, use_query_string=True)
        assert result.get("params") == {"name": "Alice"}
        assert "json" not in result

    def test_use_query_string_does_not_duplicate_already_query_annotated_params(self) -> None:
        """Test that params already routed to query (via annotation) are not duplicated"""
        endpoint = _make_endpoint({"page": Annotated[int, Query()], "name": str})
        result = endpoint_call_util.generate_rest_func_params(
            endpoint, {"page": 1, "name": "Alice"}, {}, use_query_string=True
        )
        assert result.get("params") == {"page": 1, "name": "Alice"}
        assert "json" not in result

    def test_file_instance_goes_to_files(self) -> None:
        """Test that a `File` instance is placed in the `files` key for multipart upload"""
        endpoint = _make_endpoint({"document": File})
        the_file = File("doc.pdf", b"content", "application/pdf")
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"document": the_file}, {})
        assert "files" in result
        assert "document" in result["files"]

    def test_file_typed_field_with_non_file_value_goes_to_files_without_explicit_content_type(
        self,
    ) -> None:
        """Test that a File-typed field receiving a non-File value still goes to `files` when no
        explicit Content-Type header is set"""
        endpoint = _make_endpoint({"document": File})
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"document": b"raw"}, {})
        assert "files" in result
        assert "document" in result["files"]

    def test_file_typed_field_with_non_file_value_goes_to_data_with_explicit_content_type(
        self,
    ) -> None:
        """Test that a File-typed field with an explicit Content-Type sends its value to `data`"""
        endpoint = _make_endpoint({"document": File})
        result = endpoint_call_util.generate_rest_func_params(
            endpoint,
            {"document": b"raw"},
            {},
            headers={"Content-Type": "application/octet-stream"},
        )
        assert result.get("data") == {"document": b"raw"}
        assert "files" not in result

    def test_string_raw_data_with_endpoint_content_type_injects_header(self) -> None:
        """Test that a raw-string `data` raw-option triggers Content-Type header injection"""
        endpoint = _make_endpoint({}, content_type="text/plain")
        # Pass `data` as a raw httpx option (not an endpoint param) so it lands as a string
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {}, data="raw text body")
        assert result["data"] == "raw text body"
        assert result.get("headers", {}).get("Content-Type") == "text/plain"

    def test_bytes_raw_data_with_endpoint_content_type_injects_header(self) -> None:
        """Test that a raw-bytes `data` raw-option triggers Content-Type header injection"""
        endpoint = _make_endpoint({}, content_type="application/octet-stream")
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {}, data=b"raw bytes body")
        assert result["data"] == b"raw bytes body"
        assert result.get("headers", {}).get("Content-Type") == "application/octet-stream"

    def test_dict_data_does_not_trigger_content_type_injection(self) -> None:
        """Test that a dict `data` raw-option (not str/bytes) does not inject a Content-Type header"""
        endpoint = _make_endpoint({}, content_type="text/plain")
        result = endpoint_call_util.generate_rest_func_params(endpoint, {}, {}, data={"key": "val"})
        assert "headers" not in result

    def test_explicit_content_type_header_blocks_endpoint_content_type_injection(self) -> None:
        """Test that an explicit Content-Type in raw_options prevents endpoint.content_type injection"""
        endpoint = _make_endpoint({}, content_type="text/plain")
        result = endpoint_call_util.generate_rest_func_params(
            endpoint, {}, {}, data="raw text", headers={"Content-Type": "text/csv"}
        )
        # "text/csv" (from raw_options) is retained; "text/plain" (endpoint.content_type) is not injected
        assert result["headers"]["Content-Type"] == "text/csv"

    def test_union_annotated_field_routes_by_matching_variant(self) -> None:
        """Test that a union-of-Annotated field uses the variant whose type matches the value.

        Each variant carries a distinct `Alias` so the resolved param key in the result reveals
        which variant was actually selected. Both arms include `Query` so `get_annotated_type`
        captures them as a tuple and triggers the variant-matching path.
        """
        endpoint = _make_endpoint(
            {"param": Annotated[str, Query(), Alias("str_param")] | Annotated[int, Query(), Alias("int_param")]}
        )
        # "hello" is str → matches first variant → Alias resolves key to "str_param"
        result_str = endpoint_call_util.generate_rest_func_params(endpoint, {"param": "hello"}, {})
        assert result_str.get("params") == {"str_param": "hello"}

        # 42 is int → matches second variant → Alias resolves key to "int_param"
        result_int = endpoint_call_util.generate_rest_func_params(endpoint, {"param": 42}, {})
        assert result_int.get("params") == {"int_param": 42}

    def test_union_annotated_field_no_match_logs_warning_and_uses_first_variant(self, mocker: MockerFixture) -> None:
        """Test that a value matching no union-Annotated variant logs a warning and falls back to the first.

        The union-matching branch is triggered when `get_annotated_type` with filter
        `["query", Alias, Query]` returns a tuple, i.e. when multiple `Annotated[]` arms each
        contain at least one matching metadata element.
        """
        endpoint = _make_endpoint({"param": Annotated[str, Query()] | Annotated[int, Query()]})
        mock_log = mocker.patch.object(endpoint_call_util, "logger")
        # [1, 2] matches neither str nor int → warning + fallback to first variant
        result = endpoint_call_util.generate_rest_func_params(endpoint, {"param": [1, 2]}, {})
        mock_log.warning.assert_called_once()
        assert "matches none of them" in mock_log.warning.call_args[0][0]
        # First variant is Annotated[str, Query()] → is_query_param → goes to params
        assert result.get("params") == {"param": [1, 2]}

    def test_unmodeled_param_on_multipart_endpoint_falls_through_to_data(self) -> None:
        """Test that an unmodeled param on a multipart endpoint is routed to `data` without crashing."""
        endpoint = _make_endpoint({"file": File})
        result = endpoint_call_util.generate_rest_func_params(
            endpoint,
            {"file": File("test.txt", b"hello", "text/plain"), "extra_field": "unexpected"},
            session_headers={},
        )
        assert "files" in result
        assert result.get("data") == {"extra_field": "unexpected"}

    def test_multiple_unmodeled_params_on_multipart_endpoint_all_go_to_data(self) -> None:
        """Test that multiple unmodeled params on a multipart endpoint are all handled without crashing"""
        endpoint = _make_endpoint({"file": File})
        result = endpoint_call_util.generate_rest_func_params(
            endpoint,
            {
                "file": File("test.txt", b"hello", "text/plain"),
                "unknown_a": "val_a",
                "unknown_b": 123,
            },
            session_headers={},
        )
        assert "files" in result
        assert result.get("data") == {"unknown_a": "val_a", "unknown_b": 123}

    def test_raw_options_param_name_does_not_appear_in_json_or_data(self) -> None:
        """Test that `endpoint_params["raw_options"]` is intercepted and not forwarded to json/data

        When "raw_options" appears as an endpoint param key, the branch re-applies the
        function's own **raw_options kwargs to rest_func_params. The intercepted key itself
        must not leak into `json` or `data`.
        """
        endpoint = _make_endpoint({})
        result = endpoint_call_util.generate_rest_func_params(
            endpoint, {"raw_options": "ignored"}, session_headers={}, timeout=30
        )
        assert result["timeout"] == 30
        assert "raw_options" not in result.get("json", {})
        assert "raw_options" not in result.get("data", {})
