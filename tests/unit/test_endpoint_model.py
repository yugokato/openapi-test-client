"""Unit tests for openapi/utils/endpoint_model.py (spec → EndpointModel creation) and the runtime
model property on the OpenAPI EndpointFunc."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from api_client_core.endpoints.utils.param_type import get_annotated_type
from common_libs.clients.rest_client import RestResponse

from openapi_test_client.libraries import EndpointFunc, endpoint
from openapi_test_client.libraries.base import BaseOpenAPI, OpenAPIClient
from openapi_test_client.libraries.types import (
    ENDPOINT_FUNC_CONTROL_KWARGS,
    Alias,
    EndpointModel,
    File,
    Query,
    Unset,
)
from openapi_test_client.libraries.utils.endpoint_model import create_endpoint_model_from_spec

pytestmark = [pytest.mark.unittest]


def _make_endpoint_func(api_client: OpenAPIClient, method: str, path: str) -> Any:
    """Create a minimal EndpointFunc instance for the given method and path."""

    class _TempAPI(BaseOpenAPI):
        TAGs = ("Test",)
        app_name = api_client.app_name

    # Dynamically attach an endpoint with the requested method and path
    raw_func = lambda self: None
    raw_func.__name__ = "test_endpoint"
    raw_func.__qualname__ = "_TempAPI.test_endpoint"
    raw_func.__annotations__ = {"return": RestResponse}

    decorated = getattr(endpoint, method)(path)(raw_func)
    setattr(_TempAPI, "test_endpoint", decorated)
    instance = _TempAPI(api_client)
    return instance.test_endpoint


class TestCreateEndpointModelFromSpec:
    """Tests for create_endpoint_model_from_spec()"""

    def test_query_params_parsed_for_get_endpoint(self, api_client: OpenAPIClient) -> None:
        """Test that query parameters from the spec are parsed into the EndpointModel"""
        api_spec = {
            "paths": {
                "/v1/items": {
                    "get": {
                        "parameters": [
                            {"name": "page", "in": "query", "schema": {"type": "integer"}},
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        ]
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "get", "/v1/items")
        model = create_endpoint_model_from_spec(ef, api_spec)

        assert issubclass(model, EndpointModel)
        fields = model.__dataclass_fields__
        assert "page" in fields
        assert "limit" in fields
        assert fields["page"].default is Unset
        assert fields["limit"].default is Unset

    def test_path_params_parsed_with_path_metadata(self, api_client: OpenAPIClient) -> None:
        """Test that path parameters are parsed with the 'path' metadata flag set"""
        api_spec = {
            "paths": {
                "/v1/items/{item_id}": {
                    "get": {
                        "parameters": [
                            {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        ]
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "get", "/v1/items/{item_id}")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "item_id" in fields
        assert fields["item_id"].metadata.get("path") is True

    def test_request_body_params_parsed(self, api_client: OpenAPIClient) -> None:
        """Test that requestBody schema properties are parsed into the EndpointModel"""
        api_spec = {
            "paths": {
                "/v1/users": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name"],
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/users")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "name" in fields
        assert "email" in fields

    def test_header_and_cookie_params_skipped(self, api_client: OpenAPIClient) -> None:
        """Test that 'header' and 'cookies' parameters are ignored during parsing"""
        api_spec = {
            "paths": {
                "/v1/data": {
                    "get": {
                        "parameters": [
                            {"name": "X-Api-Key", "in": "header", "schema": {"type": "string"}},
                            {"name": "session", "in": "cookies", "schema": {"type": "string"}},
                            {"name": "page", "in": "query", "schema": {"type": "integer"}},
                        ]
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "get", "/v1/data")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "X-Api-Key" not in fields
        assert "session" not in fields
        assert "page" in fields

    def test_undocumented_path_params_auto_detected(self, api_client: OpenAPIClient) -> None:
        """Test that path placeholders missing from 'parameters' are auto-detected and added"""
        api_spec: dict[str, Any] = {
            "paths": {
                "/v1/users/{user_id}/orders/{order_id}": {
                    "get": {
                        # Deliberately omit path params from spec
                        "parameters": []
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "get", "/v1/users/{user_id}/orders/{order_id}")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "user_id" in fields
        assert "order_id" in fields
        assert fields["user_id"].metadata.get("path") is True
        assert fields["order_id"].metadata.get("path") is True

    def test_file_params_detected_from_multipart_binary(self, api_client: OpenAPIClient) -> None:
        """Test that multipart/form-data params with format 'binary' are typed as File"""
        api_spec = {
            "paths": {
                "/v1/uploads": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "multipart/form-data": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "file": {"type": "string", "format": "binary"},
                                            "description": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/uploads")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "file" in fields
        assert fields["file"].type is File or (
            # Optional[File] when not required. types.UnionType has no __origin__ before 3.14
            File in getattr(fields["file"].type, "__args__", ())
        )
        assert "description" in fields

    def test_non_form_content_type_wrapped_in_data_key(self, api_client: OpenAPIClient) -> None:
        """Test that non-form content types (e.g. application/octet-stream) wrap the schema in a 'data' key"""
        api_spec = {
            "paths": {
                "/v1/raw": {
                    "post": {
                        "requestBody": {
                            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
                        }
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/raw")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "data" in fields

    def test_non_get_query_params_annotated_with_query_marker(self, api_client: OpenAPIClient) -> None:
        """Test that query params on non-GET endpoints are annotated with the Query marker"""

        api_spec = {
            "paths": {
                "/v1/items": {
                    "post": {
                        "parameters": [
                            {"name": "format", "in": "query", "schema": {"type": "string"}},
                        ]
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/items")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        assert "format" in fields
        annotated_meta = get_annotated_type(fields["format"].type)
        if annotated_meta is not None:
            assert any(isinstance(m, Query) for m in annotated_meta.__metadata__)

    def test_model_has_no_path_param_for_get_endpoint_without_path(self, api_client: OpenAPIClient) -> None:
        """Test that a simple GET with no path variables and no params yields an empty model"""
        api_spec: dict[str, Any] = {"paths": {"/v1/health": {"get": {"parameters": []}}}}
        ef = _make_endpoint_func(api_client, "get", "/v1/health")
        model = create_endpoint_model_from_spec(ef, api_spec)

        # Only path params and body/query params — should be empty
        non_path_fields = {name: f for name, f in model.__dataclass_fields__.items() if not f.metadata.get("path")}
        assert non_path_fields == {}

    @pytest.mark.parametrize("reserved_name", sorted(ENDPOINT_FUNC_CONTROL_KWARGS))
    def test_field_named_after_control_kwarg_is_aliased(self, api_client: OpenAPIClient, reserved_name: str) -> None:
        """Test that a spec param whose name matches an endpoint-function control kwarg is aliased.

        This is a regression test for the split-core refactor. Before the fix, `validate` was a
        keyword-only parameter of EndpointFunc.__call__ and was therefore part of the reserved set
        returned by get_reserved_param_names(). After the split, `validate` was moved into the
        OpenAPI request_wrapper and was no longer in the core reserved set — so a spec param named
        `validate` would no longer be aliased. At runtime, the request_wrapper would silently pop
        it as a control kwarg, making it impossible to ever send a real `validate` API parameter.
        """
        api_spec = {
            "paths": {
                "/v1/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            reserved_name: {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/items")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        aliased_name = f"{reserved_name}_"
        assert reserved_name not in fields, (
            f"Control kwarg '{reserved_name}' must be aliased to avoid collision with the endpoint "
            "function machinery that pops it from kwargs before the API call is made."
        )
        assert aliased_name in fields, f"Expected aliased field '{aliased_name}' in model fields"
        # The aliased field must carry Alias metadata pointing back to the original wire name
        field_type = fields[aliased_name].type
        annotated = get_annotated_type(field_type)
        assert annotated is not None
        alias_metadata = [m for m in annotated.__metadata__ if isinstance(m, Alias)]
        assert alias_metadata, f"No Alias metadata found on aliased field '{aliased_name}'"
        assert alias_metadata[0].value == reserved_name

    @pytest.mark.parametrize("reserved_name", ["Format", "Constraint", "ParamModel"])
    def test_field_named_after_openapi_annotation_type_is_aliased(
        self, api_client: OpenAPIClient, reserved_name: str
    ) -> None:
        """Test that a body parameter whose name matches an OpenAPI annotation type is aliased.

        This is a regression test for the split-core refactor. Before the fix, the OpenAPI spec path
        routed top-level endpoint fields through core's build_endpoint_model, which only knew about
        core's reserved names (Alias, Query, File, …) and missed OpenAPI-specific ones such as
        Format, Constraint, ParamModel, and PydanticModel. A param named e.g. "Format" would not be
        aliased and would collide with the `from ...openapi.types import Format` line in generated code.
        """
        api_spec = {
            "paths": {
                "/v1/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            reserved_name: {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        ef = _make_endpoint_func(api_client, "post", "/v1/items")
        model = create_endpoint_model_from_spec(ef, api_spec)

        fields = model.__dataclass_fields__
        # The field should be stored under the aliased name (e.g. "Format_"), not the raw reserved name
        assert reserved_name not in fields, (
            f"Field '{reserved_name}' must be aliased to avoid collision with the imported type of the same name"
        )
        aliased_name = f"{reserved_name}_"
        assert aliased_name in fields, f"Expected aliased field '{aliased_name}' in model fields"
        # The aliased field must carry Alias metadata pointing back to the original name
        field_type = fields[aliased_name].type
        annotated = get_annotated_type(field_type)
        assert annotated is not None
        alias_metadata = [m for m in annotated.__metadata__ if isinstance(m, Alias)]
        assert alias_metadata, f"No Alias metadata found on field '{aliased_name}'"
        assert alias_metadata[0].value == reserved_name


class TestRuntimeEndpointModel:
    """Tests for the runtime .model property on OpenAPI EndpointFunc.

    The .model property is used at runtime (not just at code-gen time) to build an EndpointModel
    from the function signature. The OpenAPI EndpointFunc overrides core's implementation to inject
    the OpenAPI-aware field-name sanitizer, which additionally covers OpenAPI annotation type names
    (Format, Constraint, ParamModel, …), dict method names, and OpenAPI-specific control kwargs
    (validate, …).

    These are regression tests for the split-core refactor (commit 4851ebb): before the fix, the
    runtime signature path silently used core's weaker sanitizer and missed those reserved names.
    """

    def _make_endpoint_func_with_params(self, api_client: OpenAPIClient, **param_annotations: Any) -> Any:
        """Create an OpenAPI EndpointFunc whose signature declares the given keyword parameters."""

        class _TempAPI(BaseOpenAPI):
            TAGs = ("Test",)
            app_name = api_client.app_name

        def raw_func(self: Any) -> RestResponse: ...

        raw_func.__name__ = "test_endpoint"
        raw_func.__qualname__ = "_TempAPI.test_endpoint"
        raw_func.__annotations__ = {**param_annotations, "return": RestResponse}

        params = [inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        for name, annotation in param_annotations.items():
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=Unset, annotation=annotation))
        raw_func.__signature__ = inspect.Signature(params, return_annotation=RestResponse)  # type: ignore[attr-defined]

        decorated = endpoint.post("/v1/test")(raw_func)
        setattr(_TempAPI, "test_endpoint", decorated)
        instance = _TempAPI(api_client)
        return instance.test_endpoint

    @pytest.mark.parametrize("reserved_name", sorted(ENDPOINT_FUNC_CONTROL_KWARGS))
    def test_runtime_model_aliases_openapi_control_kwargs(self, api_client: OpenAPIClient, reserved_name: str) -> None:
        """Test that the runtime .model property aliases params named after OpenAPI control kwargs.

        This is a regression test for the split-core refactor: after the split, the validate kwarg
        moved from core into the OpenAPI request_wrapper. Core's sanitizer no longer knew about it,
        so a hand-written endpoint with a param named 'validate' would not be aliased and the
        request_wrapper would silently consume it instead of forwarding it as an API parameter.
        """
        ef = self._make_endpoint_func_with_params(api_client, **{reserved_name: str})
        assert isinstance(ef, EndpointFunc)

        model = ef.model
        assert issubclass(model, EndpointModel)
        fields = model.__dataclass_fields__
        aliased_name = f"{reserved_name}_"
        assert reserved_name not in fields, (
            f"Control kwarg '{reserved_name}' must be aliased by the runtime .model property "
            "to avoid collision with the OpenAPI request_wrapper machinery."
        )
        assert aliased_name in fields, f"Expected aliased field '{aliased_name}' in runtime model fields"
        field_type = fields[aliased_name].type
        annotated = get_annotated_type(field_type)
        assert annotated is not None
        alias_metadata = [m for m in annotated.__metadata__ if isinstance(m, Alias)]
        assert alias_metadata, f"No Alias metadata found on aliased field '{aliased_name}'"
        assert alias_metadata[0].value == reserved_name

    @pytest.mark.parametrize("reserved_name", ["Format", "Constraint", "ParamModel"])
    def test_runtime_model_aliases_openapi_annotation_type_names(
        self, api_client: OpenAPIClient, reserved_name: str
    ) -> None:
        """Test that the runtime .model property aliases params named after OpenAPI annotation types.

        This is a regression test for the split-core refactor: core's sanitizer only knew about core
        type names (Alias, Query, …) and missed OpenAPI-specific ones such as Format, Constraint, and
        ParamModel. A hand-written endpoint with a param named e.g. 'Format' would not be aliased,
        potentially colliding with the imported type of the same name in generated code.
        """
        ef = self._make_endpoint_func_with_params(api_client, **{reserved_name: str})
        assert isinstance(ef, EndpointFunc)

        model = ef.model
        assert issubclass(model, EndpointModel)
        fields = model.__dataclass_fields__
        aliased_name = f"{reserved_name}_"
        assert reserved_name not in fields, (
            f"OpenAPI annotation type name '{reserved_name}' must be aliased by the runtime .model property "
            "to avoid collision with the imported type of the same name."
        )
        assert aliased_name in fields, f"Expected aliased field '{aliased_name}' in runtime model fields"
        field_type = fields[aliased_name].type
        annotated = get_annotated_type(field_type)
        assert annotated is not None
        alias_metadata = [m for m in annotated.__metadata__ if isinstance(m, Alias)]
        assert alias_metadata, f"No Alias metadata found on aliased field '{aliased_name}'"
        assert alias_metadata[0].value == reserved_name
